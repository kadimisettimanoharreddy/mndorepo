import { useState, useEffect } from 'react'
import {
  Box,
  Grid,
  Card,
  CardContent,
  Typography,
  Chip,
  Button,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  IconButton,
  Alert,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Snackbar,
  CircularProgress
} from '@mui/material';
import {
  Build,
  Computer,
  Security,
  Launch,
  Refresh,
  Delete,
  CheckCircle,
  Add,
  PendingActions,
  Error as ErrorIcon,
  HourglassEmpty,
  Storage,
  Functions,
  Cloud
} from '@mui/icons-material';
import { useAuth } from '../../contexts/AuthContext';
import { infrastructureAPI } from '../../services/api';

interface Request {
  id: string;
  request_identifier: string;
  cloud_provider: string;
  environment: string;
  resource_type: string;
  status: string;
  created_at: string;
  resources?: {
    console_url?: string;
    service_type?: string;
    instance_id?: string;
    ip_address?: string;
    bucket_name?: string;
    bucket_arn?: string;
    function_name?: string;
    function_arn?: string;
    function_url?: string;
    resource_name?: string;
    region?: string;
  };
}

export default function Dashboard() {
  const [requests, setRequests] = useState<Request[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [clearDialogOpen, setClearDialogOpen] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [clearSuccess, setClearSuccess] = useState(false);
  const [lastUpdateTime, setLastUpdateTime] = useState<Date>(new Date());

  const { user, loading: userLoading } = useAuth();

  // Debug user data and handle authentication
  useEffect(() => {
    console.log('Dashboard - User data:', user);
    console.log('Dashboard - User loading:', userLoading);
    
    // If not loading and no user, redirect to login
    if (!userLoading && !user) {
      console.log('Dashboard - No user found, should redirect to login');
      // The Layout component handles this redirect
    }
  }, [user, userLoading]);

  useEffect(() => {
    // Always load from localStorage first to prevent data loss
    const loadFromCache = () => {
      try {
        const cached = localStorage.getItem('dashboard_requests');
        if (cached) {
          const parsedRequests = JSON.parse(cached);
          if (Array.isArray(parsedRequests)) {
            console.log('Loading cached requests:', parsedRequests.length);
            setRequests(parsedRequests);
            setLoading(false);
            return true;
          }
        }
      } catch (e) {
        console.error('Failed to load from cache:', e);
      }
      return false;
    };
    
    // Load cache first, then fetch fresh data
    const hasCache = loadFromCache();
    fetchRequests(); // Always fetch fresh data

    const chatCleared = localStorage.getItem('chatCleared');
    if (chatCleared) {
      fetchRequests();
      localStorage.removeItem('chatCleared');
    }

    const pollInterval = setInterval(() => fetchRequestsSilently(), 30000);
    
    // Listen for real-time request updates with duplicate prevention
    const processedUpdates = new Set<string>();
    
    const handleRequestUpdate = (event: CustomEvent) => {
      const updatedRequest = event.detail;
      const updateId = `${updatedRequest.request_identifier}_${updatedRequest.status}_${Date.now()}`;
      
      // Prevent duplicate updates
      if (processedUpdates.has(updateId)) {
        console.log('🚫 Duplicate request update blocked:', updateId);
        return;
      }
      processedUpdates.add(updateId);
      
      // Clean up old update IDs
      if (processedUpdates.size > 50) {
        const ids = Array.from(processedUpdates);
        processedUpdates.clear();
        ids.slice(-25).forEach(id => processedUpdates.add(id));
      }
      
      console.log('📊 Processing request update:', updatedRequest.request_identifier, updatedRequest.status);
      
      setRequests(prevRequests => {
        const updated = prevRequests.map(req => 
          req.request_identifier === updatedRequest.request_identifier 
            ? { ...req, ...updatedRequest }
            : req
        );
        
        // Add if doesn't exist
        const exists = prevRequests.some(req => req.request_identifier === updatedRequest.request_identifier);
        if (!exists) {
          const newRequests = [updatedRequest, ...updated];
          // Save to localStorage immediately
          localStorage.setItem('dashboard_requests', JSON.stringify(newRequests));
          return newRequests;
        }
        
        // Save updated requests to localStorage
        localStorage.setItem('dashboard_requests', JSON.stringify(updated));
        return updated;
      });
      setLastUpdateTime(new Date());
    };
    
    window.addEventListener('requestUpdate', handleRequestUpdate as EventListener);
    
    return () => {
      clearInterval(pollInterval);
      window.removeEventListener('requestUpdate', handleRequestUpdate as EventListener);
    };
  }, []);

  const fetchRequests = async () => {
    try {
      setLoading(true);
      console.log('Fetching requests from API...');
      const response = await infrastructureAPI.getRequests();
      console.log('API Response:', response);
      
      const allRequests = response.data?.requests || response.data || [];
      const safeRequests = Array.isArray(allRequests) ? allRequests : [];
      
      console.log('Processed requests:', safeRequests.length);
      setRequests(safeRequests);
      setLastUpdateTime(new Date());
      setError('');
      
      // Always save to localStorage
      localStorage.setItem('dashboard_requests', JSON.stringify(safeRequests));
      localStorage.setItem('dashboard_last_fetch', Date.now().toString());
      console.log('Saved to localStorage:', safeRequests.length, 'requests');
      
    } catch (err: any) {
      console.error('Failed to fetch requests:', err);
      setError(`Failed to fetch requests: ${err.message}`);
      
      // Try to load from cache on error
      const cached = localStorage.getItem('dashboard_requests');
      if (cached) {
        try {
          const cachedRequests = JSON.parse(cached);
          setRequests(Array.isArray(cachedRequests) ? cachedRequests : []);
          console.log('Loaded from cache after error:', cachedRequests.length);
        } catch {
          setRequests([]);
        }
      } else {
        setRequests([]);
      }
    } finally {
      setLoading(false);
    }
  };

  const fetchRequestsSilently = async () => {
    try {
      const response = await infrastructureAPI.getRequests();
      const allRequests = response.data?.requests || response.data || [];
      const safeRequests = Array.isArray(allRequests) ? allRequests : [];
      
      // Filter recent requests like in main fetch
      const thirtyDaysAgo = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000);
      const recentRequests = safeRequests.filter(req => {
        const createdDate = new Date(req.created_at.endsWith('Z') ? req.created_at : req.created_at + 'Z');
        return createdDate > thirtyDaysAgo;
      }).slice(0, 50);
      
      if (JSON.stringify(recentRequests) !== JSON.stringify(requests)) {
        setRequests(recentRequests);
        setLastUpdateTime(new Date());
        // Save to localStorage with timestamp
        try {
          localStorage.setItem('dashboard_requests', JSON.stringify(recentRequests));
          localStorage.setItem('dashboard_last_fetch', Date.now().toString());
        } catch (e) {
          console.error('Failed to save to localStorage during silent fetch');
        }
      }
    } catch (err) {
      console.error('Silent fetch failed:', err);
    }
  };

  const clearHistory = async () => {
    try {
      setClearing(true);
      await infrastructureAPI.clearUserRequests();
      setRequests([]);
      // Clear localStorage when user manually clears history
      localStorage.removeItem('dashboard_requests');
      localStorage.removeItem('dashboard_last_fetch');
      setClearDialogOpen(false);
      setClearSuccess(true);
    } catch (error) {
      console.error('Failed to clear requests');
      setError('Failed to clear requests');
    } finally {
      setClearing(false);
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'Success':
      case 'deployed': return 'success';
      case 'Pending Approval':
      case 'pending': return 'warning';
      case 'PR Pending':
      case 'pr_created': return 'info';
      case 'Failed':
      case 'failed': return 'error';
      default: return 'default';
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'Success':
      case 'deployed': return <CheckCircle fontSize="small" />;
      case 'PR Pending':
      case 'pr_created': return <HourglassEmpty fontSize="small" />;
      case 'Pending Approval':
      case 'pending': return <PendingActions fontSize="small" />;
      case 'Failed':
      case 'failed': return <ErrorIcon fontSize="small" />;
      default: return null;
    }
  };

  const renderStatusCell = (request: Request) => {
    const getResourceInfo = () => {
      if (!request.resources) return null;
      
      const { service_type, resource_name, instance_id, bucket_name, function_name } = request.resources;
      
      if (service_type === 'ec2' && instance_id) {
        return `Instance: ${instance_id}`;
      } else if (service_type === 's3' && bucket_name) {
        return `Bucket: ${bucket_name}`;
      } else if (service_type === 'lambda' && function_name) {
        return `Function: ${function_name}`;
      } else if (resource_name) {
        return `Resource: ${resource_name}`;
      }
      return null;
    };

    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
          {getStatusIcon(request.status)}
          <Chip label={request.status.replace('_',' ').toUpperCase()} size="small" color={getStatusColor(request.status)} />
          {request.status === 'Success' && request.resources?.console_url && (
            <IconButton size="small" onClick={() => {
              const url = request.resources!.console_url;
              if (url && (url.startsWith('https://console.aws.amazon.com/') || url.startsWith('https://aws.amazon.com/'))) {
                window.open(url, '_blank', 'noopener,noreferrer');
              }
            }} title="Open AWS Console">
              <Launch fontSize="small" />
            </IconButton>
          )}
        </Box>
        {request.status === 'Success' && getResourceInfo() && (
          <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.7rem' }}>
            {getResourceInfo()}
          </Typography>
        )}
      </Box>
    );
  };

  const formatRelativeTime = (dateString: string) => {
    const now = new Date();
    // Parse UTC timestamp correctly
    const created = new Date(dateString.endsWith('Z') ? dateString : dateString + 'Z');
    
    // Ensure we have valid dates
    if (isNaN(created.getTime())) {
      return 'Just now';
    }
    
    // Calculate difference in milliseconds (current time - created time)
    const diffMs = now.getTime() - created.getTime();
    const seconds = Math.floor(Math.abs(diffMs) / 1000);
    const mins = Math.floor(seconds / 60);
    const hours = Math.floor(mins / 60);
    const days = Math.floor(hours / 24);
    
    // Handle future dates (clock skew)
    if (diffMs < 0) return 'Just now';
    
    if (seconds < 60) return 'Just now';
    if (mins < 60) return `${mins}m ago`;
    if (hours < 24) return `${hours}h ago`;
    if (days < 7) return `${days}d ago`;
    return created.toLocaleDateString();
  };

  // Update relative times every minute and force re-render
  useEffect(() => {
    const interval = setInterval(() => {
      setLastUpdateTime(new Date());
      // Force component re-render for time updates
      setRequests(prev => [...prev]);
    }, 60000);
    return () => clearInterval(interval);
  }, []);

  const formatDateTime = (dateString: string) => {
    return new Date(dateString).toLocaleString();
  };

  if (loading || userLoading) return <Box sx={{ display:'flex', justifyContent:'center', alignItems:'center', height:'100vh' }}><CircularProgress /></Box>;
  
  if (!user) {
    return (
      <Box sx={{ p: 3, textAlign: 'center' }}>
        <Typography variant="h5" color="error" sx={{ mb: 2 }}>
          Authentication Required
        </Typography>
        <Typography variant="body1" sx={{ mb: 2 }}>
          Please log in to access the dashboard.
        </Typography>
        <Button variant="contained" onClick={() => window.location.href = '/login'}>
          Go to Login
        </Button>
      </Box>
    );
  }

  return (
    <Box sx={{ p:3, backgroundColor:'#f0f8ff', minHeight:'100vh' }}>
      <Box sx={{ display:'flex', justifyContent:'space-between', alignItems:'center', mb:2 }}>
        <Box>
          <Typography variant="h4" color="#1565c0" fontWeight="bold">Infrastructure Dashboard</Typography>
          <Typography variant="h6" color="#424242" sx={{ mb: 1 }}>
            Welcome back, {user?.name || 'User'}! 👋
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Ready to manage your cloud infrastructure? Your environment access is shown below.
          </Typography>
        </Box>
        <Box sx={{ textAlign:'right' }}>
          <Typography variant="caption" color="text.secondary" display="block">Last Updated: {lastUpdateTime.toLocaleTimeString()}</Typography>
          <Typography variant="caption" color="text.secondary">Auto-refreshes every 30s</Typography>
        </Box>
      </Box>

      {error && <Alert severity="error" sx={{mb:3}} onClose={()=>setError('')}>{error}</Alert>}

      <Grid container spacing={3}>
        <Grid item xs={12} md={6}>
          <Card sx={{ borderLeft:'4px solid #4caf50', boxShadow:'0 4px 12px rgba(0,0,0,0.1)', borderRadius:2, backgroundColor:'#f1f8e9' }}>
            <CardContent>
              <Typography variant="h6" color="#2e7d32"><Security sx={{mr:1}}/>Environment Access</Typography>
              {user?.environment_access && Object.entries(user.environment_access).filter(([_,v])=>v).map(([env])=>(
                <Chip key={env} label={env.toUpperCase()} size="small" color={env==='prod'?'error':env==='qa'?'warning':'success'} sx={{mr:0.5, mb:0.5,fontWeight:600}} />
              ))}
              <Typography variant="caption" color="text.secondary" display="block">Department: <strong>{user?.department || 'Unknown'}</strong></Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={6}>
          <Card sx={{ borderLeft:'4px solid #2196f3', boxShadow:'0 4px 12px rgba(0,0,0,0.1)', borderRadius:2, backgroundColor:'#e3f2fd' }}>
            <CardContent>
              <Typography variant="h6" color="#1565c0"><Build sx={{mr:1}}/>Infrastructure Stats</Typography>
              <Box sx={{ display:'flex', justifyContent:'space-between', mt:2 }}>
                <Box textAlign="center">
                  <Typography variant="h4" color="#4caf50">
                    {Array.isArray(requests) ? requests.filter(r=>r.status==='Success'||r.status==='deployed').length : 0}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">Active Resources</Typography>
                  <Box sx={{ display: 'flex', gap: 0.5, justifyContent: 'center', mt: 0.5 }}>
                    {Array.isArray(requests) && [
                      { type: 'ec2', icon: <Computer fontSize="small" />, count: requests.filter(r => (r.status === 'Success' || r.status === 'deployed') && r.resource_type === 'ec2').length },
                      { type: 's3', icon: <Storage fontSize="small" />, count: requests.filter(r => (r.status === 'Success' || r.status === 'deployed') && r.resource_type === 's3').length },
                      { type: 'lambda', icon: <Functions fontSize="small" />, count: requests.filter(r => (r.status === 'Success' || r.status === 'deployed') && r.resource_type === 'lambda').length }
                    ].filter(service => service.count > 0).map(service => (
                      <Box key={service.type} sx={{ display: 'flex', alignItems: 'center', gap: 0.2 }}>
                        {service.icon}
                        <Typography variant="caption">{service.count}</Typography>
                      </Box>
                    ))}
                  </Box>
                </Box>
                <Box textAlign="center">
                  <Typography variant="h4" color="#ff9800">
                    {Array.isArray(requests) ? requests.filter(r=>r.status==='pending'||r.status==='pr_created'||r.status==='Pending Approval'||r.status==='PR Pending').length : 0}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">Pending Requests</Typography>
                </Box>
              </Box>
              <Button variant="contained" startIcon={<Add />} onClick={()=>window.location.href='/chat'} fullWidth sx={{mt:2, backgroundColor:'#1976d2'}}>New Request</Button>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12}>
          <Card sx={{ boxShadow:'0 4px 12px rgba(0,0,0,0.1)', borderRadius:2, backgroundColor:'#fff' }}>
            <CardContent>
              <Box sx={{ display:'flex', justifyContent:'space-between', mb:2 }}>
                <Typography variant="h6" color="#1565c0">Infrastructure Requests</Typography>
                <Box>
                  <IconButton onClick={()=>fetchRequests()}><Refresh/></IconButton>
                  {Array.isArray(requests) && requests.length>0 && <Button variant="outlined" startIcon={<Delete/>} color="error" size="small" onClick={()=>setClearDialogOpen(true)} disabled={clearing}>Clear History</Button>}
                </Box>
              </Box>

              <TableContainer>
                <Table>
                  <TableHead>
                    <TableRow sx={{ backgroundColor:'#e3f2fd' }}>
                      <TableCell><strong>Request ID</strong></TableCell>
                      <TableCell><strong>Cloud</strong></TableCell>
                      <TableCell><strong>Environment</strong></TableCell>
                      <TableCell><strong>Type</strong></TableCell>
                      <TableCell><strong>Status</strong></TableCell>
                      <TableCell><strong>Created</strong></TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {!Array.isArray(requests) || requests.length===0 ? (
                      <TableRow><TableCell colSpan={6} align="center">No infrastructure requests found.</TableCell></TableRow>
                    ) : requests.map(r=>(
                      <TableRow key={r.id} hover>
                        <TableCell>{r.request_identifier.split('_').slice(-2).join('_')}</TableCell>
                        <TableCell><Chip label={r.cloud_provider.toUpperCase()} size="small" color={r.cloud_provider==='aws'?'warning':'info'} /></TableCell>
                        <TableCell><Chip label={r.environment.toUpperCase()} size="small" color={r.environment==='prod'?'error':r.environment==='qa'?'warning':'success'} /></TableCell>
                        <TableCell>
                          <Box sx={{display:'flex', alignItems:'center'}}>
                            {r.resource_type === 'ec2' && <Computer sx={{mr:1,fontSize:16,color:'#666'}}/>}
                            {r.resource_type === 's3' && <Storage sx={{mr:1,fontSize:16,color:'#666'}}/>}
                            {r.resource_type === 'lambda' && <Functions sx={{mr:1,fontSize:16,color:'#666'}}/>}
                            {!['ec2', 's3', 'lambda'].includes(r.resource_type) && <Cloud sx={{mr:1,fontSize:16,color:'#666'}}/>}
                            {r.resource_type.toUpperCase()}
                          </Box>
                        </TableCell>
                        <TableCell>{renderStatusCell(r)}</TableCell>
                        <TableCell>
                          <Typography variant="body2" color="text.secondary" title={formatDateTime(r.created_at)}>
                            {new Date(r.created_at).toLocaleDateString()}
                            <br/>
                            <Typography variant="caption">{formatRelativeTime(r.created_at)}</Typography>
                          </Typography>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Dialog open={clearDialogOpen} onClose={()=>setClearDialogOpen(false)}>
        <DialogTitle>Clear Request History</DialogTitle>
        <DialogContent>
          <Typography>This will permanently clear all your infrastructure requests from the dashboard. This action cannot be undone.</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={()=>setClearDialogOpen(false)}>Cancel</Button>
          <Button onClick={clearHistory} color="error" variant="contained" disabled={clearing}>
            {clearing ? 'Clearing...' : 'Clear History'}
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar open={clearSuccess} autoHideDuration={3000} onClose={()=>setClearSuccess(false)} anchorOrigin={{vertical:'bottom',horizontal:'center'}}>
        <Alert onClose={()=>setClearSuccess(false)} severity="success">Request history cleared successfully!</Alert>
      </Snackbar>
    </Box>
  );
}