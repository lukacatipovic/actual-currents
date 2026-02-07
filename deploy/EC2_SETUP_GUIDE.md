# Actual Currents - EC2 Deployment Guide

## Prerequisites

- AWS account with access to the `actual-currents-data` S3 bucket (us-east-2)
- SSH key pair for EC2 access
- GitHub repo URL for the project

## Step 1: Create IAM Role

Create an IAM role for EC2 with S3 read access:

1. Go to **IAM > Roles > Create Role**
2. Trusted entity: **AWS Service > EC2**
3. Attach policy: **AmazonS3ReadOnlyAccess** (or create a custom policy scoped to `actual-currents-data`)
4. Name it: `actual-currents-ec2-role`

Custom policy (more restrictive):
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": ["s3:GetObject", "s3:ListBucket"],
            "Resource": [
                "arn:aws:s3:::actual-currents-data",
                "arn:aws:s3:::actual-currents-data/*"
            ]
        }
    ]
}
```

## Step 2: Launch EC2 Instance

1. Go to **EC2 > Launch Instance**
2. Settings:
   - **Name**: actual-currents
   - **AMI**: Amazon Linux 2023
   - **Instance type**: `t3.small` (2 vCPU, 2 GB RAM)
     - The dataset is ~267 MB compressed on disk, ~670 MB uncompressed in RAM. Peak ~1.2 GB during loading.
     - For extra headroom, use `t3.medium` (4 GB RAM, ~$30/month).
   - **Key pair**: Select your SSH key
   - **Security Group**: Create new with:
     - SSH (port 22) from your IP
     - HTTP (port 80) from anywhere (0.0.0.0/0)
   - **IAM instance profile**: Select `actual-currents-ec2-role`
   - **Storage**: 20 GB gp3 (default is fine, Docker images need ~5 GB)

3. Launch and note the **Public IPv4 address**

## Step 3: Initial Setup

SSH into the instance and run the setup script:

```bash
ssh -i your-key.pem ec2-user@<EC2_PUBLIC_IP>

# Download and run setup script (one-liner)
curl -sL https://raw.githubusercontent.com/<your-username>/actual-currents/main/deploy/ec2-setup.sh | bash -s -- https://github.com/<your-username>/actual-currents.git
```

Or manually:
```bash
ssh -i your-key.pem ec2-user@<EC2_PUBLIC_IP>

# Install Docker and dependencies
sudo dnf update -y
sudo dnf install -y docker git
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker ec2-user

# Install Docker Compose
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m)" -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Clone repo
git clone https://github.com/<your-username>/actual-currents.git
cd actual-currents

# IMPORTANT: Log out and back in for docker group
exit
```

## Step 4: Deploy

```bash
ssh -i your-key.pem ec2-user@<EC2_PUBLIC_IP>
cd actual-currents
./deploy/deploy.sh
```

First build takes 3-5 minutes (downloading Python packages). Subsequent builds are faster due to Docker layer caching.

The app takes 30-60 seconds to start as it loads the dataset from S3 into RAM.

## Step 5: Verify

Open in browser: `http://<EC2_PUBLIC_IP>`

You should see the Mapbox map. Navigate to a coastal area (e.g., Woods Hole, MA) at zoom level 8+ and the particle animation should appear.

API health check:
```bash
curl http://<EC2_PUBLIC_IP>/health
```

## Updating

After pushing changes to GitHub:

```bash
ssh -i your-key.pem ec2-user@<EC2_PUBLIC_IP>
cd actual-currents
./deploy/deploy.sh
```

## Troubleshooting

### View logs
```bash
cd ~/actual-currents
docker compose logs -f
```

### Container won't start
```bash
# Check if Docker is running
sudo systemctl status docker

# Check container status
docker compose ps

# Check build errors
docker compose build --no-cache
```

### S3 access errors
```bash
# Verify IAM role is attached
curl -s http://169.254.169.254/latest/meta-data/iam/security-credentials/

# Test S3 access from inside container
docker compose exec actual-currents python -c "
import s3fs
s3 = s3fs.S3FileSystem(anon=False)
print(s3.ls('actual-currents-data'))
"
```

### Out of memory
If the instance runs out of memory during dataset loading:
- Upgrade to `t3.medium` (4 GB RAM), or
- Add swap space:
  ```bash
  sudo fallocate -l 4G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile swap swap defaults 0 0' | sudo tee -a /etc/fstab
  ```

## Cost Estimate

- `t3.small` on-demand (us-east-2): ~$0.0208/hr = ~$15/month
- `t3.small` spot instance: ~$5-6/month (70% savings, minor interruption risk)
- 20 GB EBS: ~$1.60/month
- Data transfer: Varies by traffic
- S3 requests: Minimal (data loaded once at startup)

**Total: ~$17/month on-demand, ~$7/month with spot**

To save more, stop the instance when not in use.
