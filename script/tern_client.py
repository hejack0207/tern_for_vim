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
from tern_daemon import tern_projectDir,tern_findServer, tern_displayError, bufEncoding

opener = request.build_opener(request.ProxyHandler({}))

tern_request_timeout = None
current_buff = []
cursor = (1,1)
bufPath = None

def _tern_makeRequest(port, doc, silent=False):
  payload = json.dumps(doc)
  if not PY2:
    payload = payload.encode('utf-8')
  try:
    localhost = 'localhost'
    if platform.system().lower()=='windows':
        localhost = '127.0.0.1'
    req = opener.open("http://" + localhost + ":" + str(port) + "/", payload,
                      float(tern_request_timeout))
    result = req.read()
    if not PY2:
        result = result.decode('utf-8')
    return json.loads(result)
  except HTTPError as error:
    if not silent:
      message = error.read()
      if not PY2:
        message = message.decode('utf-8')
      tern_displayError(message)
    return None

def _tern_bufferSlice(buf, pos, end):
  text = ""
  while pos < end:
    text += buf[pos] + "\n"
    pos += 1
  return text

def _tern_fullBuffer():
  return {"type": "full",
          "name": tern_relativeFile(),
          "text": _tern_bufferSlice(current_buff, 0, len(current_buff))}

def _tern_bufferFragment():
  curRow, curCol = cursor
  line = curRow - 1
  buf = current_buff
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
          "text": _tern_bufferSlice(buf, start, end),
          "offsetLines": start}

def tern_relativeFile():
  filename = bufPath
  if PY2:
    filename = filename.decode(bufEncoding)
  if platform.system().lower()=='windows':
    return filename[len(tern_projectDir()) + 1:].replace('\\', '/')
  return filename[len(tern_projectDir()) + 1:]


def tern_runCommand(query, pos=None, fragments=True, silent=False):
  if isinstance(query, str): query = {"type": query}
  if (pos is None):
    curRow, curCol = cursor
    pos = {"line": curRow - 1, "ch": curCol}
  port, portIsOld = tern_findServer()
  if port is None: return

  doc = {"query": query, "files": []}
  if len(current_buff) > 250 and fragments:
    f = _tern_bufferFragment()
    doc["files"].append(f)
    pos = {"line": pos["line"] - f["offsetLines"], "ch": pos["ch"]}
    fname, sendingFile = ("#0", False)
  else:
    doc["files"].append(_tern_fullBuffer())
    fname, sendingFile = ("#0", True)
  query["file"] = fname
  query["end"] = pos
  query["lineCharPositions"] = True

  data = None
  try:
    data = _tern_makeRequest(port, doc, silent)
    if data is None: return None
  except:
    pass

  if data is None and portIsOld:
    try:
      port, portIsOld = tern_findServer(port)
      if port is None: return
      data = _tern_makeRequest(port, doc, silent)
      if data is None: return None
    except Exception as e:
      if not silent:
        tern_displayError(e)

  return data

def tern_sendBuffer(files=None):
  port, _portIsOld = tern_findServer()
  if port is None: return False
  try:
    _tern_makeRequest(port, {"files": files or [_tern_fullBuffer()]}, True)
    return True
  except:
    return False

