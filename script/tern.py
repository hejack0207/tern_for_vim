import os, platform, subprocess, webbrowser, json, re, time
import sys
import urllib2 as request
from urllib2 import HTTPError

from itertools import groupby

opener = request.build_opener(request.ProxyHandler({}))

def tern_refs():
  data = tern_runCommand("refs", fragments=False)
  if data is None: return

  refs = []
  for ref in data["refs"]:
    lnum     = ref["start"]["line"] + 1
    col      = ref["start"]["ch"] + 1
    filename = tern_projectFilePath(ref["file"])
    name     = data["name"]
    text     = vim.eval("getbufline('" + filename + "'," + str(lnum) + ")")
    refs.append({"lnum": lnum,
                 "col": col,
                 "filename": filename,
                 "text": name + " (file not loaded)" if len(text)==0 else text[0]})
  #vim.command("call setloclist(0," + json.dumps(refs) + ") | lopen")
  return json.dumps(refs)

def tern_lookupType():
  data = tern_runCommand("type")
  if data: tern_echoWrap(data.get("type", ""))

def tern_lookupArgumentHints(fname, apos, curRow, curCol):
  data = tern_runCommand({"type": "type", "preferFunction": True},
                         {"line": curRow - 1, "ch": apos},
                         True, True)
  if data: tern_echoWrap(data.get("type", ""),name=fname)

def tern_lookupDefinition(cmd):
  data = tern_runCommand("definition", fragments=False)
  if data is None: return

  if "file" in data:
    lnum     = data["start"]["line"] + 1
    col      = data["start"]["ch"] + 1
    filename = data["file"]

    if cmd == "edit" and filename == tern_relativeFile():
      vim.command("normal! m`")
      vim.command("call cursor(" + str(lnum) + "," + str(col) + ")")
    else:
      vim.command(cmd + " +call\ cursor(" + str(lnum) + "," + str(col) + ") " +
        tern_projectFilePath(filename).replace(" ", "\\ "))
  elif "url" in data:
    print("see " + data["url"])
  else:
    print("no definition found")

def tern_lookupDocumentation(browse=False):
  data = tern_runCommand("documentation")
  if data is None: return

  doc = data.get("doc")
  url = data.get("url")
  if url:
    if browse:
      savout = os.dup(1)
      os.close(1)
      os.open(os.devnull, os.O_RDWR)
      try:
        result = webbrowser.open(url)
      finally:
        os.dup2(savout, 1)
        return result
    doc = ((doc and doc + "\n\n") or "") + "See " + url
  if doc:
    #vim.command("call tern#PreviewInfo(" + json.dumps(doc, ensure_ascii=False) + ")")
    return json.dumps(doc,ensure)
  else:
    print("no documentation found")
    return None

def tern_ensureCompletionCached(ternLastCompletionPos, curRow, curCol, curLine,ternRequestQuery,ternCompletionQuery):
  cached = ternLastCompletionPos

  if (curRow == int(cached["row"]) and curCol >= int(cached["end"]) and
      curLine[0:int(cached["end"])] == cached["word"] and
      (not re.match(".*\\W", curLine[int(cached["end"]):curCol]))):
    return

  if ternCompletionQuery is None:
    ternCompletionQuery = dict()

  completionQuery = dict({"type": "completions", "types": True, "docs": True}, **ternCompletionQuery)

  data = tern_runCommand(completionQuery, {"line": curRow - 1, "ch": curCol})
  if data is None: return

  completions = []
  for rec in data["completions"]:
    completions.append({"word": rec["name"],
                        "menu": tern_asCompletionIcon(rec.get("type")),
                        "info": tern_typeDoc(rec) })
  #vim.command("let b:ternLastCompletion = " + json.dumps(completions))
  start, end = (data["start"]["ch"], data["end"]["ch"])
  #vim.command("let b:ternLastCompletionPos = " + json.dumps({
  #  "row": curRow,
  #  "start": start,
  #  "end": end,
  #  "word": curLine[0:end]
  #}))
  return json.dumps(completions),json.dumps({
    "row": curRow,
    "start": start,
    "end": end,
    "word": curLine[0:end]
  }))

def tern_sendBufferIfDirty(ternInsertActiveDefined, ternInsertActive, ternBufferSentAt):
  if (ternInsertActiveDefined == "1" and
      ternInsertActive == "0"):
    curSeq = vim.eval("undotree()['seq_cur']")
    if curSeq > ternBufferSentAt and tern_sendBuffer():
      #vim.command("let b:ternBufferSentAt = " + str(curSeq))
      return str(curSeq)
    else:
      return None

def tern_killServers():
  for project in _tern_projects.values():
    tern_killServer(project)

def tern_displayError(err):
  print(str(err))

def tern_makeRequest(port, doc, timeout, silent=False):
  payload = json.dumps(doc)
  try:
    localhost = 'localhost'
    if platform.system().lower()=='windows':
        localhost = '127.0.0.1'
    req = opener.open("http://" + localhost + ":" + str(port) + "/", payload,
                      timeout)
    result = req.read()
    return json.loads(result)
  except HTTPError as error:
    if not silent:
      message = error.read()
      tern_displayError(message)
    return None

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

def tern_projectDir(ternProjectDir,mydir, pathEnocoding):
  cur = ternProjectDir
  if cur: return cur

  projectdir = ""
  mydir = mydir.decode(pathEnocoding)
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

  return (projectdir,json.dumps(projectdir))

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

def tern_startServer(project, ternCommand, ternArgs):
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

def tern_killServer(project):
  if project.proc is None: return
  project.proc.stdin.close()
  project.proc.wait()
  project.proc = None

def tern_relativeFile(bufferPath,encoding):
  filename = bufferPath
  filename = filename.decode(encoding)
  if platform.system().lower()=='windows':
    return filename[len(tern_projectDir()) + 1:].replace('\\', '/')
  return filename[len(tern_projectDir()) + 1:]

def tern_bufferSlice(buf, pos, end):
  text = ""
  while pos < end:
    text += buf[pos] + "\n"
    pos += 1
  return text

def tern_fullBuffer(bufferText):
  return {"type": "full",
          "name": tern_relativeFile(),
          "text": tern_bufferSlice(bufferText, 0, len(bufferText))}

def tern_bufferFragment(curRow, curCol, bufferText):
  line = curRow - 1
  buf = bufferText
  minIndent = None
  start = None

  for i in range(max(0, line - 50), line):
    if not re.match(".*\\bfunction\\b", buf[i]): continue
    indent = len(re.match("^\\s*", buf[i]).group(0))
    if minIndent is None or indent <= minIndent:
      minIndent = indent
      start = i

  if start is None: start = max(0, line - 50)
  end = min(len(buf) - 1, line + 20)
  return {"type": "part",
          "name": tern_relativeFile(),
          "text": tern_bufferSlice(buf, start, end),
          "offsetLines": start}

def tern_runCommand(query, curRow, curCol, ternBufferSentAt, bufferText, ternInsertActive, pos=None, fragments=True, silent=False):
  if isinstance(query, str): query = {"type": query}
  if (pos is None):
    pos = {"line": curRow - 1, "ch": curCol}
  port, portIsOld = tern_findServer()
  if port is None: return
  curSeq = vim.eval("undotree()['seq_cur']")

  doc = {"query": query, "files": []}
  if curSeq == ternBufferSentAt:
    fname, sendingFile = (tern_relativeFile(), False)
  elif len(bufferText) > 250 and fragments:
    f = tern_bufferFragment()
    doc["files"].append(f)
    pos = {"line": pos["line"] - f["offsetLines"], "ch": pos["ch"]}
    fname, sendingFile = ("#0", False)
  else:
    doc["files"].append(tern_fullBuffer())
    fname, sendingFile = ("#0", True)
  query["file"] = fname
  query["end"] = pos
  query["lineCharPositions"] = True

  data = None
  try:
    data = tern_makeRequest(port, doc, silent)
    if data is None: return None
  except:
    pass

  if data is None and portIsOld:
    try:
      port, portIsOld = tern_findServer(port)
      if port is None: return
      data = tern_makeRequest(port, doc, silent)
      if data is None: return None
    except Exception as e:
      if not silent:
        tern_displayError(e)

  if sendingFile and ternInsertActive == "0":
    return (data, str(curSeq))
  else:
    return (data, None)

def tern_sendBuffer(files=None):
  port, _portIsOld = tern_findServer()
  if port is None: return False
  try:
    tern_makeRequest(port, {"files": files or [tern_fullBuffer()]}, True)
    return True
  except:
    return False

def ternasCompletionIcon(type, ternShowSignatureInPum):
  if type is None or type == "?": return "(?)"
  if type.startswith("fn("):
    if ternShowSignatureInPum == "0":
      return "(fn)"
    else:
      return type
  if type.startswith("["): return "([])"
  if type == "number": return "(num)"
  if type == "string": return "(str)"
  if type == "bool": return "(bool)"
  return "(obj)"

def tern_typeDoc(rec):
  tp = rec.get("type")
  result = rec.get("doc", " ")
  if tp and tp != "?":
     result = tp + "\n" + result
  return result

def tern_echoWrap(data, name="", columns):
  text = data
  if len(name) > 0:
    text = name+": " + text
  col = int(columns)-23
  if len(text) > col:
    text = text[0:col]+"..."
  print(text.encode('utf-8'))

def tern_projectFilePath(path):
  return os.path.join(tern_projectDir(), path)

# Copied here because Python 2.6 and lower don't have it built in, and
# python 3.0 and higher don't support old-style cmp= args to the sort
# method. There's probably a better way to do this...
def tern_cmp_to_key(mycmp):
  class K(object):
    def __init__(self, obj, *args):
      self.obj = obj
    def __lt__(self, other):
      return mycmp(self.obj, other.obj) < 0
    def __gt__(self, other):
      return mycmp(self.obj, other.obj) > 0
    def __eq__(self, other):
      return mycmp(self.obj, other.obj) == 0
    def __le__(self, other):
      return mycmp(self.obj, other.obj) <= 0
    def __ge__(self, other):
      return mycmp(self.obj, other.obj) >= 0
    def __ne__(self, other):
      return mycmp(self.obj, other.obj) != 0
  return K

def tern_rename(newName):
  data = tern_runCommand({"type": "rename", "newName": newName}, fragments=False)
  if data is None: return

  def mycmp(a,b):
    return (cmp(a["file"], b["file"]) or
            cmp(a["start"]["line"], b["start"]["line"]) or
            cmp(a["start"]["ch"], b["start"]["ch"]))
  data["changes"].sort(key=tern_cmp_to_key(mycmp))
  changes_byfile = groupby(data["changes"]
                          ,key=lambda c: tern_projectFilePath(c["file"]))

  name = data["name"]
  changes, external = ([], [])
  for file, filechanges in changes_byfile:

    buffer = None
    for buf in vim.buffers:
      if buf.name == file:
        buffer = buf

    if buffer is not None:
      lines = buffer
    else:
      with open(file, "r") as f:
        lines = f.readlines()
    for linenr, linechanges in groupby(filechanges, key=lambda c: c["start"]["line"]):
      text = lines[linenr]
      offset = 0
      changed = []
      for change in linechanges:
        colStart = change["start"]["ch"]
        colEnd = change["end"]["ch"]
        text = text[0:colStart + offset] + newName + text[colEnd + offset:]
        offset += len(newName) - len(name)
        changed.append({"lnum": linenr + 1,
                        "col": colStart + 1 + offset,
                        "filename": file})
      for change in changed:
        if buffer is not None:
          lines[linenr] = change["text"] = text
        else:
          change["text"] = "[not loaded] " + text
          lines[linenr] = text
      changes.extend(changed)
    if buffer is None:
      with open(file, "w") as f:
        f.writelines(lines)
      external.append({"name": file, "text": "".join(lines), "type": "full"})
  if len(external):
    tern_sendBuffer(external)

  if vim.eval("g:tern_show_loc_after_rename") == '1':
    vim.command("call setloclist(0," + json.dumps(changes) + ") | lopen")
