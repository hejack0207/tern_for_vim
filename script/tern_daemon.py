import os, platform, subprocess, webbrowser, json, re, time
import sys
PY2 = int(sys.version[0]) == 2
if PY2:
    import urllib2 as request
    from urllib2 import HTTPError
else:  # Py3
    from urllib import request
    from urllib.error import HTTPError

    def cmp(a, b):
        if a < b:
            return -1
        elif a > b:
            return 1
        else:
            return 0

from itertools import groupby

ternProjectDir = None
bufDir = None
bufEncoding = None
ternCommand = None
ternArgs = None

def tern_displayError(err):
  print(str(err))

# Prefixed with _ to influence destruction order. See
# http://docs.python.org/2/reference/datamodel.html#object.__del__
_tern_projects = {}

class Project(object):
  def __init__(self, dir):
    self.dir = dir
    self.port = None
    self.proc = None
    self.last_failed = 0

  def __del__(self):
    tern_killServer(self)

def tern_projectDir():
  cur = ternProjectDir
  if cur: return cur

  projectdir = ""
  mydir = bufDir
  if PY2:
    mydir = mydir.decode(bufEncoding)
  if not os.path.isdir(mydir): return ""

  if mydir:
    projectdir = mydir
    while True:
      parent = os.path.dirname(mydir[:-1])
      if not parent:
        break
      if os.path.isfile(os.path.join(mydir, ".tern-project")):
        projectdir = mydir
        break
      mydir = parent

  ternProjectDir = projectdir
  return projectdir

def tern_startServer(project):
  if time.time() - project.last_failed < 30: return None

  win = platform.system() == "Windows"
  env = None
  if platform.system() == "Darwin":
    env = os.environ.copy()
    env["PATH"] += ":/usr/local/bin"
  command = ternCommand + ternArgs
  try:
    proc = subprocess.Popen(command,
                            cwd=project.dir, env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, shell=win)
  except Exception as e:
    tern_displayError("Failed to start server: " + str(e))
    return None
  output = ""
  while True:
    line = proc.stdout.readline().decode('utf8')
    if not line:
      tern_displayError("Failed to start server" + (output and ":\n" + output))
      project.last_failed = time.time()
      return None
    match = re.match("Listening on port (\\d+)", line)
    if match:
      port = int(match.group(1))
      project.port = port
      project.proc = proc
      return port
    else:
      output += line

def tern_findServer(ignorePort=False):
  dir = tern_projectDir()
  if not dir: return (None, False)
  project = _tern_projects.get(dir, None)
  if project is None:
    project = Project(dir)
    _tern_projects[dir] = project
  if project.port is not None and project.port != ignorePort:
    return (project.port, True)

  portFile = os.path.join(dir, ".tern-port")
  if os.path.isfile(portFile):
    port = int(open(portFile, "r").read())
    if port != ignorePort:
      project.port = port
      return (port, True)
  return (tern_startServer(project), False)

def tern_killServer(project):
  if project.proc is None: return
  project.proc.stdin.close()
  project.proc.wait()
  project.proc = None

def tern_killServers():
  for project in _tern_projects.values():
    tern_killServer(project)

