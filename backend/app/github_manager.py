# backend/app/github_manager.py
import os
import logging
import asyncio
import tempfile
import shutil
from typing import Optional, Dict, Any
from pathlib import Path
import time

from .config import GITHUB_TOKEN, GITHUB_REPO_OWNER, GITHUB_REPO_NAME
from .database import SyncSessionLocal
from .models import InfrastructureRequest, User
from sqlalchemy import select

from .terraform_manager import find_repo_root, get_user_active_environment

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class GitHubManager:
    def __init__(self):
        self.github_token = GITHUB_TOKEN
        self.repo_owner = GITHUB_REPO_OWNER
        self.repo_name = GITHUB_REPO_NAME
        self.base_branch = "main"

    async def create_pull_request(self, request_identifier: str) -> Optional[int]:
        repo_path = None
        try:
            logger.info("Creating GitHub PR for request %s", request_identifier)
            request_details = self._get_request_details_sync(request_identifier)
            if not request_details:
                raise Exception(f"Request {request_identifier} not found")

            repo_path = await self._setup_repository()

            # Generate unique branch name with process ID and UUID
            import uuid
            import os
            timestamp = int(time.time())
            process_id = os.getpid()
            unique_id = str(uuid.uuid4())[:8]
            branch_name = f"infra-{request_identifier}-{timestamp}-{process_id}-{unique_id}"
            logger.info(f"Generated unique branch name: {branch_name} (PID: {process_id})")
            
            await self._create_branch(repo_path, branch_name)
            await self._create_terraform_files(repo_path, request_identifier, request_details)
            await self._commit_changes(repo_path, request_identifier, request_details)
            
            # Push with retry and return the final branch name used
            final_branch_name = await self._push_branch_with_retry(repo_path, branch_name)
            pr_number = await self._create_pr(request_identifier, request_details, final_branch_name)
            logger.info("Successfully created PR #%s for %s", pr_number, request_identifier)
            return pr_number

        except Exception as e:
            logger.exception("Error creating GitHub PR for %s: %s", request_identifier, e)
            raise
        finally:
            if repo_path and os.path.exists(repo_path):
                # Optional cleanup of stale branches before removing temp repo
                try:
                    await self.cleanup_stale_branches(repo_path)
                except Exception:
                    pass  # Non-critical operation
                shutil.rmtree(repo_path, ignore_errors=True)

    async def _setup_repository(self) -> str:
        temp_dir = tempfile.mkdtemp()
        repo_path = os.path.join(temp_dir, "repo")
        if not self.github_token or not self.repo_owner or not self.repo_name:
            raise Exception("GitHub configuration missing (GITHUB_TOKEN/REPO owner/name)")
        clone_url = f"https://{self.github_token}@github.com/{self.repo_owner}/{self.repo_name}.git"
        proc = await asyncio.create_subprocess_exec("git", "clone", clone_url, repo_path,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise Exception(f"Failed to clone repository: {err.decode().strip()}")
        await self._configure_git(repo_path)
        return repo_path

    async def _configure_git(self, repo_path: str):
        commands = [
            ["git", "config", "user.email", "aiops-bot@company.com"],
            ["git", "config", "user.name", "AIOps Platform Bot"]
        ]
        for cmd in commands:
            proc = await asyncio.create_subprocess_exec(*cmd, cwd=repo_path,
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            await proc.communicate()

    async def _create_branch(self, repo_path: str, branch_name: str):
        proc = await asyncio.create_subprocess_exec("git", "checkout", "-b", branch_name, cwd=repo_path,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise Exception(f"Failed to create branch {branch_name}: {err.decode().strip()}")

    async def _create_terraform_files(self, repo_path: str, request_identifier: str, request_details: Dict):
        request = request_details["request"]
        user = request_details["user"]
        params = request_details["parameters"] or {}

        repo_root = find_repo_root()
        cloud = (params.get("cloud") or getattr(request, "cloud_provider", "aws")).lower()
        
     
        env = get_user_active_environment(user, request)
        
        
        if params.get("environment"):
            requested = params.get("environment").lower()
            if user and hasattr(user, 'is_environment_active') and user.is_environment_active(requested):
                env = requested
                logger.info(f"GitHubManager: Using explicitly requested environment: {requested}")
            else:
                logger.warning(f"GitHubManager: User doesn't have access to {requested}, using {env}")

        logger.info(f"GitHubManager: using environment={env} for request={request_identifier}")

        tfvars_name = f"{request_identifier}.tfvars"
        canonical_tfvars = None
        if repo_root:
            canonical_tfvars = repo_root / "terraform" / "environments" / cloud / env / "requests" / tfvars_name

        clone_requests_dir = Path(repo_path) / "backend" / "terraform" / "environments" / cloud / env / "requests"
        clone_requests_dir.mkdir(parents=True, exist_ok=True)
        clone_tfvars_path = clone_requests_dir / tfvars_name

        if canonical_tfvars and canonical_tfvars.exists():
            shutil.copy2(canonical_tfvars, clone_tfvars_path)
            logger.info("Copied tfvars from canonical workspace: %s -> %s", canonical_tfvars, clone_tfvars_path)
            return

        backend_tfvars = Path.cwd().resolve() / "terraform" / "environments" / cloud / env / "requests" / tfvars_name
        if backend_tfvars.exists():
            shutil.copy2(backend_tfvars, clone_tfvars_path)
            logger.info("Copied tfvars from backend fallback: %s -> %s", backend_tfvars, clone_tfvars_path)
            return

        from .terraform_manager import _render_tfvars_content
        content = _render_tfvars_content(request_identifier, user, params)
        clone_tfvars_path.write_text(content, encoding="utf-8")
        logger.info("Generated tfvars in clone (fallback): %s", clone_tfvars_path)

    async def _commit_changes(self, repo_path: str, request_identifier: str, request_details: Dict):
        proc = await asyncio.create_subprocess_exec("git", "add", ".", cwd=repo_path,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await proc.communicate()

        commit_message = self._generate_commit_message(request_identifier, request_details)
        proc = await asyncio.create_subprocess_exec("git", "commit", "-m", commit_message, cwd=repo_path,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()
        if proc.returncode != 0:
            stderr_txt = err.decode().lower()
            if "nothing to commit" in stderr_txt:
                logger.info("Nothing to commit (no changes).")
            else:
                raise Exception(f"Failed to commit changes: {err.decode().strip()}")
        logger.info("Committed changes for %s", request_identifier)

    def _generate_commit_message(self, request_identifier: str, request_details: Dict) -> str:
        request = request_details["request"]
        user = request_details["user"]
        return f"Auto infra PR: {request_identifier}\n\nAuto-generated by AIOps Platform"

    async def _push_branch_with_retry(self, repo_path: str, branch_name: str) -> str:
        """Push branch with retry logic, returns the final branch name used"""
        proc = await asyncio.create_subprocess_exec("git", "fetch", "origin", cwd=repo_path,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await proc.communicate()

        current_branch = branch_name
        max_retries = 5
        
        for attempt in range(max_retries):
            proc = await asyncio.create_subprocess_exec("git", "push", "origin", current_branch, cwd=repo_path,
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, err = await proc.communicate()
            
            if proc.returncode == 0:
                logger.info("Successfully pushed branch %s to origin", current_branch)
                return current_branch
            
            error_msg = err.decode().strip()
            logger.warning(f"Push attempt {attempt + 1} failed for {current_branch}: {error_msg}")
            
            # Check if it's a branch conflict (handle various GitHub error formats)
            conflict_indicators = [
                "already exists", "cannot lock ref", "reference already exists",
                "remote rejected", "failed to push some refs"
            ]
            is_conflict = any(indicator in error_msg.lower() for indicator in conflict_indicators)
            
            if is_conflict and attempt < max_retries - 1:
                
                # Generate new unique branch name
                import uuid
                import random
                new_suffix = f"{random.randint(1000, 9999)}-{str(uuid.uuid4())[:6]}"
                old_branch = current_branch
                current_branch = f"{branch_name}-retry-{new_suffix}"
                
                logger.info(f"Branch conflict detected for {old_branch}, creating new branch: {current_branch}")
                
                # Delete the conflicting local branch if it exists
                try:
                    proc_del = await asyncio.create_subprocess_exec("git", "branch", "-D", old_branch, cwd=repo_path,
                                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    await proc_del.communicate()
                except Exception:
                    pass  # Ignore if branch doesn't exist locally
                
                # Create and checkout new branch
                proc = await asyncio.create_subprocess_exec("git", "checkout", "-b", current_branch, cwd=repo_path,
                                                            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                checkout_out, checkout_err = await proc.communicate()
                
                if proc.returncode != 0:
                    logger.error(f"Failed to create new branch {current_branch}: {checkout_err.decode()}")
                    continue
                    
                # Small delay to avoid race conditions
                await asyncio.sleep(0.5)
                continue
            
            # If it's not a branch conflict or we've exhausted retries
            if attempt == max_retries - 1:
                raise Exception(f"Failed to push branch after {max_retries} attempts. Last error: {error_msg}")
        
        raise Exception(f"Failed to push branch {current_branch}: {error_msg}")

    async def _create_pr(self, request_identifier: str, request_details: Dict, branch_name: str) -> int:
        user = request_details.get("user")
        request = request_details.get("request")
        
        # Determine service type for PR title
        service_type = "EC2"
        if request_identifier.startswith("s3_"):
            service_type = "S3"
        elif request_identifier.startswith("lambda_"):
            service_type = "Lambda"
        elif request and hasattr(request, 'resource_type'):
            service_type = request.resource_type.upper()
        
        pr_title = f"[{getattr(request,'environment','DEV').upper()}] AWS {service_type} - {request_identifier}"
        pr_body = f"Auto generated PR for {service_type} deployment\n\nRequest ID: {request_identifier}\nRequested by: {getattr(user,'email','unknown')}\n"
        
        env = os.environ.copy()
        env["GH_TOKEN"] = self.github_token or env.get("GH_TOKEN", "")
        
        # Retry PR creation in case of temporary failures
        max_retries = 3
        for attempt in range(max_retries):
            try:
                proc = await asyncio.create_subprocess_exec("gh", "pr", "create", "--title", pr_title, "--body", pr_body,
                                                            "--base", self.base_branch, "--head", branch_name,
                                                            "--repo", f"{self.repo_owner}/{self.repo_name}",
                                                            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
                out, err = await proc.communicate()
                
                if proc.returncode == 0:
                    pr_url = out.decode().strip()
                    try:
                        pr_number = int(pr_url.split("/")[-1])
                    except Exception:
                        pr_number = 0
                    logger.info("Created PR %s: %s", pr_number, pr_url)
                    return pr_number
                
                error_msg = err.decode().strip()
                if attempt < max_retries - 1:
                    logger.warning(f"PR creation attempt {attempt + 1} failed, retrying: {error_msg}")
                    await asyncio.sleep(1)
                    continue
                else:
                    raise Exception(f"Failed to create PR after {max_retries} attempts: {error_msg}")
                    
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"PR creation attempt {attempt + 1} failed with exception, retrying: {e}")
                    await asyncio.sleep(1)
                    continue
                else:
                    raise Exception(f"Failed to create PR after {max_retries} attempts: {e}")
        
        raise Exception("Failed to create PR: Maximum retries exceeded")

    def _get_request_details_sync(self, request_identifier: str) -> Dict:
        with SyncSessionLocal() as db:
            try:
                result = db.execute(
                    select(InfrastructureRequest, User)
                    .join(User)
                    .where(InfrastructureRequest.request_identifier == request_identifier)
                )
                request_data = result.first()
                
                if request_data:
                    request, user = request_data
                    return {
                        "request": request, 
                        "user": user, 
                        "parameters": request.request_parameters
                    }
                
                result = db.execute(
                    select(InfrastructureRequest)
                    .where(InfrastructureRequest.request_identifier == request_identifier)
                )
                req = result.scalar_one_or_none()
                
                if req:
                    return {
                        "request": req, 
                        "user": None, 
                        "parameters": getattr(req, "request_parameters", {})
                    }
                
                return None
                
            except Exception as e:
                logger.exception("Error in sync database lookup for %s: %s", request_identifier, e)
                return None
    
    async def cleanup_stale_branches(self, repo_path: str, max_age_hours: int = 24):
        """Clean up old infra branches to prevent accumulation"""
        try:
            # List all remote branches
            proc = await asyncio.create_subprocess_exec("git", "branch", "-r", cwd=repo_path,
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, err = await proc.communicate()
            
            if proc.returncode != 0:
                logger.warning(f"Failed to list remote branches: {err.decode()}")
                return
            
            branches = out.decode().strip().split('\n')
            infra_branches = [b.strip() for b in branches if 'origin/infra-' in b and 'retry' in b]
            
            # Delete old retry branches (these are usually from failed attempts)
            for branch in infra_branches[:10]:  # Limit to avoid too many deletions
                branch_name = branch.replace('origin/', '')
                try:
                    proc = await asyncio.create_subprocess_exec("git", "push", "origin", "--delete", branch_name, cwd=repo_path,
                                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    await proc.communicate()
                    logger.info(f"Cleaned up stale branch: {branch_name}")
                except Exception as e:
                    logger.debug(f"Could not delete branch {branch_name}: {e}")
                    
        except Exception as e:
            logger.debug(f"Branch cleanup failed (non-critical): {e}")