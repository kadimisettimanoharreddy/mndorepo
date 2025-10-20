data "aws_ami" "selected" {
  most_recent = true
  owners      = var.ami_owners
  filter {
    name   = "name"
    values = [var.ami_filter]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

data "aws_region" "current" {}

locals {
  selected_ami_id = var.ami_id != "" ? var.ami_id : data.aws_ami.selected.id
  final_key_name = var.create_new_keypair ? aws_key_pair.new[0].key_name : var.key_name
  vpc_id = var.use_existing_vpc ? var.vpc_id : data.aws_vpc.default[0].id
  subnet_id = var.use_existing_subnet ? var.subnet_id : data.aws_subnets.default[0].ids[0]
  security_group_ids = var.use_existing_sg ? [var.security_group_id] : [aws_security_group.default[0].id]
}

resource "tls_private_key" "rsa" {
  count     = var.create_new_keypair ? 1 : 0
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "new" {
  count      = var.create_new_keypair ? 1 : 0
  key_name   = var.key_name
  public_key = tls_private_key.rsa[0].public_key_openssh
  tags       = var.instance_tags
}

resource "aws_ssm_parameter" "private_key" {
  count = var.create_new_keypair ? 1 : 0
  name  = "/aiops/keypairs/${var.key_name}/private_key"
  type  = "SecureString"
  value = tls_private_key.rsa[0].private_key_pem
  tags  = var.instance_tags
}

data "aws_vpc" "default" {
  count   = var.use_existing_vpc ? 0 : 1
  default = true
}

data "aws_vpc" "existing" {
  count = var.use_existing_vpc ? 1 : 0
  id    = var.vpc_id
}

data "aws_subnets" "default" {
  count = var.use_existing_subnet ? 0 : 1
  filter {
    name   = "vpc-id"
    values = [local.vpc_id]
  }
}

resource "aws_security_group" "default" {
  count       = var.use_existing_sg ? 0 : 1
  name        = "aiops-${var.operating_system}-sg-${random_id.sg_suffix.hex}"
  description = "Security group for ${var.operating_system} instance"
  vpc_id      = local.vpc_id

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.instance_tags
}

resource "random_id" "sg_suffix" {
  byte_length = 4
}

resource "aws_instance" "main" {
  ami                    = local.selected_ami_id
  instance_type         = var.instance_type
  key_name              = local.final_key_name
  vpc_security_group_ids = local.security_group_ids
  subnet_id             = local.subnet_id
  associate_public_ip_address = var.associate_public_ip

  root_block_device {
    volume_type = "gp3"
    volume_size = var.storage_size
    encrypted   = true
  }

  tags = var.instance_tags
}