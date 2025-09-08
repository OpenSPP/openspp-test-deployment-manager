# Nginx Configuration Update - Deployment Guide

## Overview
This update addresses all nginx configuration issues reported by DevOps, including:
- Automatic hash bucket size configuration
- Both internal and external vhost generation  
- Smart error recovery and auto-fixing
- Startup reconciliation
- Better error visibility in UI

## New Components

### 1. NginxManager (`src/nginx_manager.py`)
Enhanced nginx management with:
- Auto-configures `server_names_hash_bucket_size` to 128
- Generates complete vhosts for both internal (`.openspp-test.internal`) and external (`.test.openspp.org`) domains
- Automatic error detection and recovery
- Config validation with rollback on failure
- Reconciliation to fix drift between deployments and nginx configs

### 2. Sudo Permissions Script (`scripts/setup_nginx_sudo.sh`)
Sets up proper sudoers rules for the `openspp` user to manage nginx without password.

## Deployment Steps

### 1. Update Code
```bash
# Pull latest changes
git pull origin main
```

### 2. Setup Sudo Permissions (One-time, as root)
```bash
sudo bash scripts/setup_nginx_sudo.sh
```

This allows the `openspp` user to:
- Test nginx configuration (`nginx -t`)
- Reload nginx (`nginx -s reload`, `systemctl reload nginx`)
- Manage nginx config files in `/etc/nginx/`

### 3. Restart the Service
```bash
sudo systemctl restart openspp-deployment-manager
```

### 4. Verify Nginx Base Config
The system will automatically:
- Check and update `server_names_hash_bucket_size` to 128 in `/etc/nginx/nginx.conf`
- Create backup before modifying nginx.conf
- Reconcile all deployment configs on startup

## What's Fixed

### 1. Hash Bucket Size Issue ✅
- Automatically sets `server_names_hash_bucket_size 128` in nginx.conf
- Detects hash bucket errors and auto-increases the size
- No more manual intervention needed

### 2. Missing Vhosts ✅
- Creates both internal and external vhosts for every deployment
- Internal: `deployment-id.openspp-test.internal` (no auth)
- External: `deployment-id.test.openspp.org` (with basic auth)
- Service subdomains: `mailhog-*` and `pgweb-*` for both

### 3. Validation & Reload ✅
- Tests configuration AFTER writing files
- Auto-fixes common errors (like hash bucket size)
- Rolls back changes if config is invalid
- Proper error messages with suggested fixes

### 4. Permissions ✅
- Sudo rules allow `openspp` user to manage nginx
- No password required for nginx operations
- Secure and limited to necessary commands only

### 5. Reconciliation ✅
- On startup: scans all deployments and fixes nginx configs
- Creates missing vhosts
- Removes stale configs for deleted deployments
- Ensures htpasswd files exist for all deployments

### 6. UI Improvements ✅
- Sidebar shows nginx status (running/stopped, valid/invalid)
- Shows last reload time and status
- "Reconcile Nginx" button for manual fixes
- Clear error messages when things go wrong

## Testing

After deployment, verify:

1. **Check nginx status in UI sidebar**:
   - Should show "✅ Nginx is running"
   - Should show "✅ Config is valid"

2. **Test reconciliation**:
   - Click "🔧 Reconcile Nginx" button in sidebar
   - Should show number of configs checked/created/removed

3. **Create a test deployment**:
   - Should automatically create both internal and external vhosts
   - Check both domains work:
     - Internal: `http://deployment-id.openspp-test.internal/`
     - External: `http://deployment-id.test.openspp.org/` (requires auth)

4. **Verify auto-recovery**:
   - The system should handle hash bucket size errors automatically
   - Check logs for "Auto-fix successful" messages if errors occur

## Troubleshooting

### If nginx won't reload:
1. Check nginx status in UI sidebar for error messages
2. Click "Reconcile Nginx" to fix any config issues
3. Check logs: `journalctl -u openspp-deployment-manager -n 100`

### If vhosts aren't created:
1. Ensure sudo permissions are set: `sudo -u openspp sudo nginx -t`
2. Click "Reconcile Nginx" in UI to recreate missing configs
3. Check `/etc/nginx/sites-available/` for `openspp-*.conf` files

### If internal domains don't work:
Ensure `/etc/hosts` or DNS has entries for `.openspp-test.internal` domains

## Rollback

If issues occur, the old DomainManager code is preserved:
1. Revert to previous commit
2. Restart service
3. Old domain_manager.py file is still available

## Contact

For issues or questions about this update, check:
- Logs: `journalctl -u openspp-deployment-manager -f`
- Nginx error logs: `/var/log/nginx/error.log`
- UI sidebar for nginx status and errors