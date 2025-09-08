#!/bin/bash
# ABOUTME: Setup sudo permissions for openspp user to manage nginx
# ABOUTME: Run this script as root to configure proper permissions

set -e

echo "Setting up nginx sudo permissions for openspp user..."

# Create sudoers.d file for openspp nginx permissions
SUDOERS_FILE="/etc/sudoers.d/openspp-nginx"

cat > "$SUDOERS_FILE" << 'EOF'
# OpenSPP Deployment Manager nginx permissions
# Allow openspp user to manage nginx without password

# Nginx test and reload commands
openspp ALL=(root) NOPASSWD: /usr/sbin/nginx -t
openspp ALL=(root) NOPASSWD: /usr/sbin/nginx -s reload
openspp ALL=(root) NOPASSWD: /bin/systemctl reload nginx
openspp ALL=(root) NOPASSWD: /bin/systemctl status nginx

# File operations for nginx configs
openspp ALL=(root) NOPASSWD: /bin/mv /tmp/* /etc/nginx/sites-available/*
openspp ALL=(root) NOPASSWD: /bin/mv /tmp/* /etc/nginx/htpasswd-*
openspp ALL=(root) NOPASSWD: /bin/ln -sf /etc/nginx/sites-available/* /etc/nginx/sites-enabled/*
openspp ALL=(root) NOPASSWD: /bin/rm /etc/nginx/sites-enabled/*
openspp ALL=(root) NOPASSWD: /bin/rm /etc/nginx/sites-available/openspp-*
openspp ALL=(root) NOPASSWD: /bin/rm /etc/nginx/htpasswd-*
openspp ALL=(root) NOPASSWD: /bin/chmod 644 /etc/nginx/sites-available/*
openspp ALL=(root) NOPASSWD: /bin/chmod 644 /etc/nginx/htpasswd-*

# Allow reading and modifying nginx.conf for hash bucket size fixes
openspp ALL=(root) NOPASSWD: /bin/cat /etc/nginx/nginx.conf
openspp ALL=(root) NOPASSWD: /bin/cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.backup.*
openspp ALL=(root) NOPASSWD: /bin/mv /tmp/* /etc/nginx/nginx.conf

# htpasswd command for creating auth files
openspp ALL=(root) NOPASSWD: /usr/bin/htpasswd -bn * *
EOF

# Set proper permissions on sudoers file
chmod 440 "$SUDOERS_FILE"

# Validate sudoers syntax
visudo -c -f "$SUDOERS_FILE"

if [ $? -eq 0 ]; then
    echo "✅ Sudo permissions configured successfully"
    echo ""
    echo "The openspp user can now run these commands without password:"
    echo "  - nginx -t (test configuration)"
    echo "  - nginx -s reload (reload nginx)"
    echo "  - systemctl reload nginx"
    echo "  - Manage nginx config files"
    echo ""
    echo "Test with: sudo -u openspp sudo nginx -t"
else
    echo "❌ Error in sudoers configuration"
    rm -f "$SUDOERS_FILE"
    exit 1
fi