import vim, os, platform, subprocess, webbrowser, json, re, time
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
from tern_daemon import tern_projectDir,_tern_projects,tern_killServer
from tern_client import tern_runCommand, tern_sendBuffer, tern_relativeFile

def _tern_asCompletionIcon(type):
  if type is None or type == "?": return "(?)"
  if type.startswith("fn("):
    if vim.eval("g:tern_show_signature_in_pum") == "0":
      return "(fn)"
    else:
      return type
  if type.startswith("["): return "([])"
  if type == "number": return "(num)"
  if type == "string": return "(str)"
  if type == "bool": return "(bool)"
  return "(obj)"

def _tern_typeDoc(rec):
  tp = rec.get("type")
  result = rec.get("doc", " ")
  if tp and tp != "?":
     result = tp + "\n" + result
  return result

def _tern_echoWrap(data, name=""):
  text = data
  if len(name) > 0:
    text = name+": " + text
  col = int(vim.eval("&columns"))-23
  if len(text) > col:
    text = text[0:col]+"..."
  print(text.encode('utf-8'))

def _tern_projectFilePath(path):
  return os.path.join(tern_projectDir(), path)

# Copied here because Python 2.6 and lower don't have it built in, and
# python 3.0 and higher don't support old-style cmp= args to the sort
# method. There's probably a better way to do this...
def _tern_cmp_to_key(mycmp):
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

def tern_sendBufferIfDirty():
  if (vim.eval("exists('b:ternInsertActive')") == "1" and
      vim.eval("b:ternInsertActive") == "0"):
    curSeq = vim.eval("undotree()['seq_cur']")
    if curSeq > vim.eval("b:ternBufferSentAt") and tern_sendBuffer():
      vim.command("let b:ternBufferSentAt = " + str(curSeq))

def tern_ensureCompletionCached():
  cached = vim.eval("b:ternLastCompletionPos")
  curRow, curCol = vim.current.window.cursor
  curLine = vim.current.buffer[curRow - 1]

  if (curRow == int(cached["row"]) and curCol >= int(cached["end"]) and
      curLine[0:int(cached["end"])] == cached["word"] and
      (not re.match(".*\\W", curLine[int(cached["end"]):curCol]))):
    return

  ternRequestQuery = vim.eval('g:tern_request_query')
  ternCompletionQuery = ternRequestQuery.get('completions')

  if ternCompletionQuery is None:
    ternCompletionQuery = dict()

  completionQuery = dict({"type": "completions", "types": True, "docs": True}, **ternCompletionQuery)

  data = tern_runCommand(completionQuery, {"line": curRow - 1, "ch": curCol})
  if data is None: return

  completions = []
  for rec in data["completions"]:
    completions.append({"word": rec["name"],
                        "menu": _tern_asCompletionIcon(rec.get("type")),
                        "info": _tern_typeDoc(rec) })
  vim.command("let b:ternLastCompletion = " + json.dumps(completions))
  start, end = (data["start"]["ch"], data["end"]["ch"])
  vim.command("let b:ternLastCompletionPos = " + json.dumps({
    "row": curRow,
    "start": start,
    "end": end,
    "word": curLine[0:end]
  }))

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
    vim.command("call tern#PreviewInfo(" + json.dumps(doc, ensure_ascii=False) + ")")
  else:
    print("no documentation found")

def tern_lookupType():
  data = tern_runCommand("type")
  if data: _tern_echoWrap(data.get("type", ""))

def tern_lookupArgumentHints(fname, apos):
  curRow, curCol = vim.current.window.cursor
  data = tern_runCommand({"type": "type", "preferFunction": True},
                         {"line": curRow - 1, "ch": apos},
                         True, True)
  if data: _tern_echoWrap(data.get("type", ""),name=fname)

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
        _tern_projectFilePath(filename).replace(" ", "\\ "))
  elif "url" in data:
    print("see " + data["url"])
  else:
    print("no definition found")

def tern_refs():
  data = tern_runCommand("refs", fragments=False)
  if data is None: return

  refs = []
  for ref in data["refs"]:
    lnum     = ref["start"]["line"] + 1
    col      = ref["start"]["ch"] + 1
    filename = _tern_projectFilePath(ref["file"])
    name     = data["name"]
    text     = vim.eval("getbufline('" + filename + "'," + str(lnum) + ")")
    refs.append({"lnum": lnum,
                 "col": col,
                 "filename": filename,
                 "text": name + " (file not loaded)" if len(text)==0 else text[0]})
  vim.command("call setloclist(0," + json.dumps(refs) + ") | lopen")

def tern_rename(newName):
  data = tern_runCommand({"type": "rename", "newName": newName}, fragments=False)
  if data is None: return

  def mycmp(a,b):
    return (cmp(a["file"], b["file"]) or
            cmp(a["start"]["line"], b["start"]["line"]) or
            cmp(a["start"]["ch"], b["start"]["ch"]))
  data["changes"].sort(key=_tern_cmp_to_key(mycmp))
  changes_byfile = groupby(data["changes"]
                          ,key=lambda c: _tern_projectFilePath(c["file"]))

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

def tern_killServers():
  for project in _tern_projects.values():
    tern_killServer(project)

