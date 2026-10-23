--[[--
Busca o estado do PC sem travar a leitura.

A requisicao HTTP roda num subprocesso (como o KOReader faz em outras buscas
em segundo plano); o processo principal so confere de tempos em tempos se a
resposta chegou. Se o subprocesso nao puder ser criado, faz a busca direto,
com prazo curto.
]]

local UIManager = require("ui/uimanager")
local ffiutil = require("ffi/util")
local logger = require("logger")

local Busca = {
    PRAZO = 20,              -- segundos ate desistir de uma busca
    ocupado = false,
}

--- A requisicao em si. Devolve uma tabela simples (vai pelo pipe como texto).
local function requisitar(url, token, etag)
    local socket = require("socket")
    local socketutil = require("socketutil")
    local ltn12 = require("ltn12")
    local http = require("socket.http")
    local partes = {}
    local headers = { ["Accept"] = "application/json" }
    if token and token ~= "" then headers["Authorization"] = "Bearer " .. token end
    if etag and etag ~= "" then headers["If-None-Match"] = etag end
    socketutil:set_timeout(5, 10)
    local codigo, cab, status = socket.skip(1, http.request{
        url = url,
        method = "GET",
        headers = headers,
        sink = ltn12.sink.table(partes),
    })
    socketutil:reset_timeout()
    if cab == nil then
        return { erro = tostring(codigo or status or "sem resposta") }
    end
    return {
        codigo = tonumber(codigo),
        etag = cab["etag"],
        corpo = table.concat(partes),
    }
end

-- "codigo\netag\nerro\n" .. corpo
local function empacotar(r)
    local etag = (r.etag or ""):gsub("\n", "")
    local erro = (r.erro or ""):gsub("\n", " ")
    return table.concat({ tostring(r.codigo or ""), etag, erro, "" }, "\n") .. (r.corpo or "")
end

local function desempacotar(s)
    if not s or s == "" then return { erro = "subprocesso sem resposta" } end
    local codigo, etag, erro, corpo = s:match("^([^\n]*)\n([^\n]*)\n([^\n]*)\n(.*)$")
    if not codigo then return { erro = "resposta ilegivel" } end
    return {
        codigo = tonumber(codigo),
        etag = etag ~= "" and etag or nil,
        erro = erro ~= "" and erro or nil,
        corpo = corpo,
    }
end

--[[--
Faz GET em `url` e chama `pronto(resultado)` no processo principal.
resultado: { codigo, etag, corpo } ou { erro }
Devolve false se ja havia uma busca em andamento.
]]
function Busca.get(url, token, etag, pronto)
    if Busca.ocupado then return false end
    Busca.ocupado = true

    local function terminar(r)
        Busca.ocupado = false
        pronto(r)
    end

    local pid, fd = ffiutil.runInSubProcess(function(_, escrever_fd)
        local ok, r = pcall(requisitar, url, token, etag)
        if not ok then r = { erro = tostring(r) } end
        ffiutil.writeToFD(escrever_fd, empacotar(r), true)
    end, true)

    if not pid then
        logger.warn("Claudinho: sem subprocesso, buscando direto:", fd)
        local ok, r = pcall(requisitar, url, token, etag)
        terminar(ok and r or { erro = tostring(r) })
        return true
    end

    local inicio = os.time()
    local conferir
    conferir = function()
        -- um erro aqui deixaria o Busca.ocupado preso e nenhuma busca rodaria mais
        local ok, pronta, r = pcall(function()
            if ffiutil.isSubProcessDone(pid) then
                return true, desempacotar(ffiutil.readAllFromFD(fd))
            elseif os.time() - inicio > Busca.PRAZO then
                ffiutil.terminateSubProcess(pid)
                -- recolhe o processo depois, para nao virar zumbi
                UIManager:scheduleIn(1, function() ffiutil.isSubProcessDone(pid) end)
                ffiutil.readAllFromFD(fd)
                return true, { erro = "tempo esgotado" }
            end
            return false
        end)
        if not ok then
            terminar({ erro = "falha ao ler a resposta: " .. tostring(pronta) })
        elseif pronta then
            terminar(r)
        else
            UIManager:scheduleIn(0.25, conferir)
        end
    end
    UIManager:scheduleIn(0.25, conferir)
    return true
end

-- exposto para o teste fora do Kindle
Busca._empacotar, Busca._desempacotar, Busca._requisitar = empacotar, desempacotar, requisitar

return Busca
