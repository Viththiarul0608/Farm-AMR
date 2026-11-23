// pm2 keeps the Python farm server running 24/7 and restarts it on crash or reboot.
//   npm i -g pm2
//   pm2 start ecosystem.config.js
//   pm2 save && pm2 startup     (run the command it prints, to auto-start after reboot)
module.exports = {
  apps: [{
    name: 'farm-py',
    script: 'server.py',
    interpreter: 'python3',
    env: { PORT: 3000 },
    autorestart: true,
    restart_delay: 2000,
    kill_timeout: 5000
  }]
};
