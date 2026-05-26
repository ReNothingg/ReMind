import { spawn } from 'node:child_process'

const npmCommand = process.platform === 'win32' ? 'npm.cmd' : 'npm'

const processes = [
  {
    name: 'backend',
    command: npmCommand,
    args: ['run', 'dev:backend'],
  },
  {
    name: 'frontend',
    command: npmCommand,
    args: ['run', 'dev:frontend'],
  },
]

const children = new Set()
let shuttingDown = false

function writePrefixed(name, chunk, stream) {
  const lines = chunk.toString().split(/\r?\n/)

  for (const line of lines) {
    if (line.length > 0) {
      stream.write(`[${name}] ${line}\n`)
    }
  }
}

function stopAll(signal = 'SIGTERM') {
  if (shuttingDown) {
    return
  }

  shuttingDown = true

  for (const child of children) {
    if (child.killed) {
      continue
    }

    if (process.platform !== 'win32') {
      try {
        process.kill(-child.pid, signal)
      } catch {
        child.kill(signal)
      }
    } else {
      child.kill(signal)
    }
  }
}

for (const processConfig of processes) {
  const child = spawn(processConfig.command, processConfig.args, {
    cwd: process.cwd(),
    detached: process.platform !== 'win32',
    env: process.env,
    stdio: ['inherit', 'pipe', 'pipe'],
  })

  children.add(child)

  child.stdout.on('data', (chunk) => writePrefixed(processConfig.name, chunk, process.stdout))
  child.stderr.on('data', (chunk) => writePrefixed(processConfig.name, chunk, process.stderr))

  child.on('error', (error) => {
    console.error(`[${processConfig.name}] failed to start: ${error.message}`)
    stopAll()
    process.exitCode = 1
  })

  child.on('exit', (code, signal) => {
    children.delete(child)

    if (!shuttingDown && code !== 0) {
      const reason = signal ? `signal ${signal}` : `code ${code}`
      console.error(`[${processConfig.name}] exited with ${reason}`)
      process.exitCode = code ?? 1
      stopAll()
    }
  })
}

process.on('SIGINT', () => stopAll('SIGINT'))
process.on('SIGTERM', () => stopAll('SIGTERM'))
