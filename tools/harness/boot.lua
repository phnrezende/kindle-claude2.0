--[[--
Prepara um LuaJIT puro para rodar o desenho do plugin com o Blitbuffer, o
FreeType e o RenderText de verdade do KOReader, sem o resto do KOReader.

Precisa dos fontes do KOReader e do koreader-base clonados e de um LuaJIT:
    KO=caminho/koreader KOBASE=caminho/koreader-base luajit tools/harness/render.lua ...
]]

local KO = os.getenv("KO") or error("defina KO=caminho do repositorio koreader")
local KOBASE = os.getenv("KOBASE") or error("defina KOBASE=caminho do repositorio koreader-base")
local AQUI = debug.getinfo(1, "S").source:sub(2):match("(.*/)") or "./"
local PLUGIN = AQUI .. "../../kindle/claudinho.koplugin/"

local ffi = require("ffi")
ffi.libc = ffi.libc or "gnu"
package.path = PLUGIN .. "?.lua;" .. KOBASE .. "/?.lua;" .. KO .. "/frontend/?.lua;" .. package.path

package.preload["libs/libkoreader-lfs"] = function()
    return { attributes = function() return nil end, dir = function() return function() end end }
end
package.preload["logger"] = function()
    local nada = function() end
    return { dbg = nada, info = nada, warn = function(...) io.stderr:write(table.concat({ ... }, " "), "\n") end,
        err = function(...) io.stderr:write(table.concat({ ... }, " "), "\n") end }
end
package.preload["cache"] = function()
    local Cache = {}
    function Cache:new(o) o = o or {}; o.t = {}; return setmetatable(o, { __index = Cache }) end
    function Cache:check(k) return self.t[k] end
    function Cache:insert(k, v) self.t[k] = v end
    return Cache
end
package.preload["ui/font"] = function() return { fallbacks = {} } end

-- o loadlib do KOReader procura bibliotecas em libs/; aponta para o FreeType do sistema
-- (FREETYPE=caminho escolhe outro; senao, procura nos lugares de costume)
local function achar_freetype()
    local escolhido = os.getenv("FREETYPE")
    if escolhido and escolhido ~= "" then return escolhido end
    for _, c in ipairs({ "/usr/lib/x86_64-linux-gnu/libfreetype.so.6", "/usr/lib/aarch64-linux-gnu/libfreetype.so.6",
        "/usr/lib64/libfreetype.so.6", "/usr/lib/libfreetype.so.6", "/usr/local/lib/libfreetype.so.6" }) do
        local f = io.open(c, "rb")
        if f then f:close() return c end
    end
    error("libfreetype.so.6 nao encontrada: defina FREETYPE=caminho/da/libfreetype.so.6")
end
os.execute("mkdir -p libs && ln -sf '" .. achar_freetype() .. "' libs/libfreetype.so.6")
local real_print = print
print = function() end          -- o loadlib fala muito
require("ffi/loadlib")
local BB = require("ffi/blitbuffer")
local Freetype = require("ffi/freetype")
local RT = require("ui/rendertext")
print = real_print

local FONTES = {
    inter800 = PLUGIN .. "fonts/InterTight-ExtraBold.ttf",
    inter900 = PLUGIN .. "fonts/InterTight-Black.ttf",
    mono400 = PLUGIN .. "fonts/JetBrainsMono-Regular.ttf",
    mono700 = PLUGIN .. "fonts/JetBrainsMono-Bold.ttf",
}

local function fonte(nome, px)
    px = math.max(1, math.floor(px + 0.5))
    return { ftsize = Freetype.newFaceSize(FONTES[nome], px), hash = nome .. px, orig_size = px, size = px }
end

local function salvar_pgm(bb, caminho)
    local w, h = bb:getWidth(), bb:getHeight()
    local f = assert(io.open(caminho, "wb"))
    f:write(string.format("P5\n%d %d\n255\n", w, h))
    local linha = {}
    for y = 0, h - 1 do
        for x = 0, w - 1 do
            linha[x + 1] = string.char(bb:getPixel(x, y):getColor8().a)
        end
        f:write(table.concat(linha))
    end
    f:close()
end

return { BB = BB, RT = RT, fonte = fonte, salvar_pgm = salvar_pgm, PLUGIN = PLUGIN }
