import tern_daemon
import tern_client
import vim

tern_daemon.ternProjectDir = vim.eval("b:ternProjectDir")
tern_daemon.bufDir = vim.eval("expand('%:p:h')")
tern_daemon.bufEncoding = vim.eval('&encoding')
tern_daemon.ternCommand= vim.eval("g:tern#command")
tern_daemon.ternArgs = vim.eval("g:tern#arguments")

tern_client.tern_request_timeout = vim.eval("g:tern_request_timeout")
tern_client.current_buff = vim.current.buffer
tern_client.cursor = vim.current.window.cursor
tern_client.bufPath = vim.eval("expand('%:p')")

