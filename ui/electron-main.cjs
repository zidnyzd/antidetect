const { app, BrowserWindow } = require('electron')
const path = require('path')
const { spawn } = require('child_process')
const http = require('http')

const projectRoot = path.resolve(__dirname, '..')
const pythonBin = path.join(projectRoot, 'venv', 'bin', 'python')
const iconPath = path.join(projectRoot, 'assets', 'cloakdesk-logo.png')

let backendProcess = null
let mainWindow = null

function checkBackend(callback) {
  const req = http.get('http://127.0.0.1:53200/health', (res) => {
    if (res.statusCode === 200) {
      callback(true)
    } else {
      callback(false)
    }
  })
  req.on('error', () => callback(false))
  req.setTimeout(1000, () => {
    req.destroy()
    callback(false)
  })
}

function ensureBackend(callback) {
  checkBackend((running) => {
    if (running) {
      return callback()
    }
    const py = require('fs').existsSync(pythonBin) ? pythonBin : '/usr/bin/python3'
    backendProcess = spawn(py, ['-m', 'antidetect', 'serve'], {
      cwd: projectRoot,
      env: { ...process.env, DISPLAY: process.env.DISPLAY || ':0' },
      stdio: 'ignore',
      detached: false,
    })

    let attempts = 0
    const interval = setInterval(() => {
      attempts++
      checkBackend((ok) => {
        if (ok || attempts > 35) {
          clearInterval(interval)
          callback()
        }
      })
    }, 200)
  })
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 960,
    minHeight: 600,
    title: 'CloakDesk',
    icon: iconPath,
    autoHideMenuBar: true,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  })

  mainWindow.loadURL('http://127.0.0.1:53200/#/profiles')

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

app.whenReady().then(() => {
  ensureBackend(() => {
    createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})
