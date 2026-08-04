# JK Taxi API - Deployment Guide

## Server Details

| Item | Value |
|------|-------|
| Provider | AWS EC2 |
| Instance IP | 3.7.46.116 |
| Region | ap-south-1 (Mumbai) |
| OS | Ubuntu |
| Python | 3.14 |
| Domain | api.jktaxitamilnadu.com |
| SSL | Let's Encrypt (auto-renew via Certbot) |
| Database | PostgreSQL on AWS RDS (ap-south-1) |

## Architecture

```
Client Apps (Customer/Driver)
       │
       ▼
Nginx (port 443, SSL termination)
       │
       ▼
Uvicorn (port 8000, FastAPI)
       │
       ▼
PostgreSQL (AWS RDS)
```

## SSH Access

```bash
ssh -i ~/Downloads/jk_taxi_server.pem ubuntu@3.7.46.116
```

## Directory Structure

```
/home/ubuntu/jk_taxi/
├── backend/          # FastAPI application
│   ├── app/
│   │   ├── main.py          # FastAPI app entry point
│   │   ├── api/             # Route handlers
│   │   │   ├── auth/        # Authentication (login/register)
│   │   │   ├── admin/       # Admin panel APIs
│   │   │   ├── admin_enhanced/  # Analytics, vehicle categories
│   │   │   ├── booking/     # Legacy booking
│   │   │   ├── booking_enhanced/  # V2 booking with full features
│   │   │   ├── driver/      # Driver profile/status
│   │   │   ├── driver_enhanced/  # V2 driver rides/earnings
│   │   │   ├── user/        # User profile
│   │   │   └── user_enhanced/   # V2 user features
│   │   ├── core/            # Config, security, dependencies
│   │   ├── db/              # Database connection
│   │   ├── models/          # SQLAlchemy models
│   │   └── schemas/         # Pydantic schemas
│   ├── alembic/             # Database migrations
│   └── requirements.txt
├── .env                     # Environment variables
├── venv/                    # Python virtual environment
└── web/
    ├── admin/               # Admin panel (React + Vite)
    └── portfolio/           # Marketing website
```

## Environment Variables

File: `/home/ubuntu/jk_taxi/.env`

```env
APP_NAME=JK Taxi API
DEBUG=False
API_VERSION=v1
DATABASE_URL=postgresql://postgres:<password>@<rds-host>:5432/jktaxi
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=<your-secret-key>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
STATIC_OTP=123456
ALLOWED_ORIGINS=["*"]
```

## Systemd Service

File: `/etc/systemd/system/jktaxi.service`

```ini
[Unit]
Description=JK Taxi FastAPI Backend
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/jk_taxi/backend
Environment="PATH=/home/ubuntu/jk_taxi/venv/bin"
EnvironmentFile=/home/ubuntu/jk_taxi/.env
ExecStart=/home/ubuntu/jk_taxi/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

## Nginx Configuration

File: `/etc/nginx/sites-enabled/jktaxi`

- `api.jktaxitamilnadu.com` → proxy to `127.0.0.1:8000`
- `jktaxitamilnadu.com` → static files from `/home/ubuntu/jk_taxi/web/portfolio/dist`
- SSL managed by Certbot (auto-renew)

---

## Deployment Steps

### Quick Deploy (from local machine)

```bash
# 1. Push code to GitHub
git add -A && git commit -m "your message" && git push origin main

# 2. Pull on EC2 and restart
ssh -i ~/Downloads/jk_taxi_server.pem ubuntu@3.7.46.116 \
  "cd /home/ubuntu/jk_taxi && git pull origin main && sudo systemctl restart jktaxi"
```

### Full Fresh Setup (new server)

```bash
# 1. SSH into server
ssh -i ~/Downloads/jk_taxi_server.pem ubuntu@<ip>

# 2. Install dependencies
sudo apt update && sudo apt install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx git

# 3. Clone repository
cd /home/ubuntu
git clone https://github.com/SSAKTHITSELVAN/jk_taxi.git

# 4. Create virtual environment
cd jk_taxi
python3 -m venv venv
source venv/bin/activate

# 5. Install Python packages
cd backend
pip install -r requirements.txt
pip install psycopg2-binary

# 6. Create .env file
cat > /home/ubuntu/jk_taxi/.env << 'EOF'
APP_NAME=JK Taxi API
DEBUG=False
API_VERSION=v1
DATABASE_URL=postgresql://postgres:<password>@<rds-endpoint>:5432/jktaxi
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=<generate-a-strong-key>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
STATIC_OTP=123456
ALLOWED_ORIGINS=["*"]
EOF

# 7. Create systemd service
sudo cp /dev/stdin /etc/systemd/system/jktaxi.service << 'EOF'
[Unit]
Description=JK Taxi FastAPI Backend
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/jk_taxi/backend
Environment="PATH=/home/ubuntu/jk_taxi/venv/bin"
EnvironmentFile=/home/ubuntu/jk_taxi/.env
ExecStart=/home/ubuntu/jk_taxi/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# 8. Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable jktaxi
sudo systemctl start jktaxi

# 9. Configure Nginx
# Add server block for api.jktaxitamilnadu.com proxying to localhost:8000
sudo nano /etc/nginx/sites-enabled/jktaxi

# 10. Setup SSL
sudo certbot --nginx -d api.jktaxitamilnadu.com

# 11. Verify
curl https://api.jktaxitamilnadu.com/health
```

### Database Migrations

```bash
# SSH into server
ssh -i ~/Downloads/jk_taxi_server.pem ubuntu@3.7.46.116

# Activate venv
cd /home/ubuntu/jk_taxi/backend
source /home/ubuntu/jk_taxi/venv/bin/activate

# Run migration (add new columns)
python3 -c "
from app.db.database import engine
from sqlalchemy import text
with engine.connect() as conn:
    conn.execute(text('ALTER TABLE drivers ADD COLUMN IF NOT EXISTS license_document VARCHAR(500)'))
    conn.execute(text('ALTER TABLE drivers ADD COLUMN IF NOT EXISTS aadhar_document VARCHAR(500)'))
    conn.execute(text('ALTER TABLE drivers ADD COLUMN IF NOT EXISTS verification_notes VARCHAR(500)'))
    conn.execute(text('ALTER TABLE rides_enhanced ADD COLUMN IF NOT EXISTS cancellation_reason VARCHAR(500)'))
    conn.execute(text('''
        CREATE TABLE IF NOT EXISTS ride_cancellations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            ride_id UUID NOT NULL,
            cancelled_by VARCHAR(10) NOT NULL,
            canceller_id UUID NOT NULL,
            reason VARCHAR(100) NOT NULL,
            custom_reason TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    '''))
    conn.commit()
    print('Done')
"
```

---

## Service Management

```bash
# Check status
sudo systemctl status jktaxi

# Restart
sudo systemctl restart jktaxi

# View logs (live)
sudo journalctl -u jktaxi -f

# View last 50 lines
sudo journalctl -u jktaxi --no-pager -n 50

# Stop
sudo systemctl stop jktaxi
```

---

## API Endpoints

### Base URL: `https://api.jktaxitamilnadu.com`

#### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/auth/register | Customer registration |
| POST | /api/auth/login | Customer login |
| POST | /api/auth/driver/register | Driver registration |
| POST | /api/auth/driver/login | Driver login |
| POST | /api/auth/admin/login | Admin login |

#### Driver (V2)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/v2/driver/location | Update GPS location |
| GET | /api/v2/driver/rides/available | Get nearby pending rides |
| GET | /api/v2/driver/rides/active | Get current active ride |
| POST | /api/v2/driver/rides/{id}/accept | Accept a ride |
| POST | /api/v2/driver/rides/{id}/decline | Decline a pending ride |
| POST | /api/v2/driver/rides/{id}/verify-otp | Verify customer OTP |
| POST | /api/v2/driver/rides/{id}/start | Start ride (requires OTP) |
| POST | /api/v2/driver/rides/{id}/complete | Complete ride (500m check) |
| POST | /api/v2/driver/rides/{id}/complete?force=true | Force complete |
| POST | /api/v2/driver/rides/{id}/cancel | Cancel with reason |
| POST | /api/v2/driver/rides/{id}/reject | Reject assigned ride |
| GET | /api/v2/driver/rides/history | Completed rides list |
| GET | /api/v2/driver/earnings | Earnings breakdown |

#### Booking (V2)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/v2/bookings | Create new booking |
| GET | /api/v2/bookings/active | Get active booking |
| POST | /api/v2/bookings/calculate-fare | Calculate fare estimate |
| GET | /api/v2/bookings/vehicle-categories | Available vehicle types |
| GET | /api/v2/bookings/active/tracking | Live driver tracking |
| POST | /api/v2/bookings/{id}/cancel | Cancel booking |

#### Admin
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/admin/dashboard/stats | Dashboard statistics |
| GET | /api/admin/drivers | List all drivers |
| PUT | /api/admin/drivers/{id}/unblock | Approve/activate driver |
| PUT | /api/admin/drivers/{id}/block | Deactivate driver |
| GET | /api/v2/admin/drivers/earnings | All drivers earnings |
| GET | /api/v2/admin/analytics/overview | Revenue analytics |

---

## Troubleshooting

### Backend won't start
```bash
# Check logs
sudo journalctl -u jktaxi --since "5 min ago"

# Common issues:
# - Missing column: Run migration SQL above
# - Port in use: sudo lsof -i :8000
# - Python import error: Check venv is activated
```

### 502 Bad Gateway
```bash
# Uvicorn crashed - check and restart
sudo systemctl status jktaxi
sudo systemctl restart jktaxi
```

### Database column missing
```bash
# Connect and add column
ssh -i ~/Downloads/jk_taxi_server.pem ubuntu@3.7.46.116
cd /home/ubuntu/jk_taxi/backend
source /home/ubuntu/jk_taxi/venv/bin/activate
python3 -c "
from app.db.database import engine
from sqlalchemy import text
with engine.connect() as conn:
    conn.execute(text('ALTER TABLE <table> ADD COLUMN IF NOT EXISTS <column> <type>'))
    conn.commit()
"
```

### SSL certificate renewal
```bash
# Auto-renew is configured, but to force:
sudo certbot renew --force-renewal
sudo systemctl reload nginx
```
