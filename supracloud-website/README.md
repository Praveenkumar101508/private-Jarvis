# SupraCloud Website

This folder contains the SupraCloud marketing/product website.

## How to populate this folder

The SupraCloud website lives at https://github.com/Praveenkumar101508/supracloud

Run this from the root of private-Jarvis to pull in the website files:

```bash
# One-time setup — merge supracloud repo into this subfolder
git remote add supracloud https://github.com/Praveenkumar101508/supracloud.git
git fetch supracloud
git read-tree --prefix=supracloud-website/ -u supracloud/main
git commit -m "feat: merge supracloud website into subfolder"
```

Or simply copy files manually:
```bash
git clone https://github.com/Praveenkumar101508/supracloud.git /tmp/supracloud
cp -r /tmp/supracloud/* ./supracloud-website/
```

## Running standalone

```bash
cd supracloud-website
docker build -t supracloud-website .
docker run -p 3001:80 supracloud-website
```

Or via the main docker compose:
```bash
docker compose up supracloud-website -d
# Visit http://localhost:3001
```
