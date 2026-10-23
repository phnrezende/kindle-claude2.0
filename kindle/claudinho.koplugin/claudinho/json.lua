--[[--
Decodificador JSON minimo, so para o estado do Claudinho.

O KOReader tem bibliotecas de JSON, mas variam entre versoes; este arquivo
pequeno nao depende de nenhuma. `null` vira nil.
]]

local json = {}

local escapes = { ['"'] = '"', ["\\"] = "\\", ["/"] = "/", b = "\b", f = "\f", n = "\n", r = "\r", t = "\t" }

local function utf8(cp)
    if cp < 0x80 then
        return string.char(cp)
    elseif cp < 0x800 then
        return string.char(0xC0 + math.floor(cp / 0x40), 0x80 + cp % 0x40)
    elseif cp < 0x10000 then
        return string.char(0xE0 + math.floor(cp / 0x1000), 0x80 + math.floor(cp / 0x40) % 0x40, 0x80 + cp % 0x40)
    end
    return string.char(0xF0 + math.floor(cp / 0x40000), 0x80 + math.floor(cp / 0x1000) % 0x40,
        0x80 + math.floor(cp / 0x40) % 0x40, 0x80 + cp % 0x40)
end

local function erro(s, i, msg)
    error(string.format("JSON invalido na posicao %d: %s", i, msg), 0)
end

local function pular(s, i)
    return s:find("[^ \t\r\n]", i) or (#s + 1)
end

local valor

local function texto(s, i)
    local partes, j = {}, i + 1
    while true do
        local c = s:sub(j, j)
        if c == "" then erro(s, j, "texto sem fim") end
        if c == '"' then return table.concat(partes), j + 1 end
        if c == "\\" then
            local e = s:sub(j + 1, j + 1)
            if e == "u" then
                local cp = tonumber(s:sub(j + 2, j + 5), 16)
                if not cp then erro(s, j, "\\u invalido") end
                j = j + 6
                if cp >= 0xD800 and cp <= 0xDBFF and s:sub(j, j + 1) == "\\u" then
                    local baixo = tonumber(s:sub(j + 2, j + 5), 16)
                    if baixo and baixo >= 0xDC00 and baixo <= 0xDFFF then
                        cp = 0x10000 + (cp - 0xD800) * 0x400 + (baixo - 0xDC00)
                        j = j + 6
                    end
                end
                partes[#partes + 1] = utf8(cp)
            elseif escapes[e] then
                partes[#partes + 1] = escapes[e]
                j = j + 2
            else
                erro(s, j, "escape invalido")
            end
        else
            local k = s:find('["\\]', j) or (#s + 1)
            partes[#partes + 1] = s:sub(j, k - 1)
            j = k
        end
    end
end

local function numero(s, i)
    local fim = s:find("[^%d%.eE%+%-]", i) or (#s + 1)
    local n = tonumber(s:sub(i, fim - 1))
    if not n then erro(s, i, "numero invalido") end
    return n, fim
end

local function lista(s, i)
    local t, n = {}, 0
    i = pular(s, i + 1)
    if s:sub(i, i) == "]" then return t, i + 1 end
    while true do
        local v
        v, i = valor(s, i)
        n = n + 1
        t[n] = v
        i = pular(s, i)
        local c = s:sub(i, i)
        if c == "]" then return t, i + 1 end
        if c ~= "," then erro(s, i, "esperava , ou ]") end
        i = pular(s, i + 1)
    end
end

local function objeto(s, i)
    local t = {}
    i = pular(s, i + 1)
    if s:sub(i, i) == "}" then return t, i + 1 end
    while true do
        if s:sub(i, i) ~= '"' then erro(s, i, "esperava chave") end
        local k
        k, i = texto(s, i)
        i = pular(s, i)
        if s:sub(i, i) ~= ":" then erro(s, i, "esperava :") end
        local v
        v, i = valor(s, pular(s, i + 1))
        t[k] = v
        i = pular(s, i)
        local c = s:sub(i, i)
        if c == "}" then return t, i + 1 end
        if c ~= "," then erro(s, i, "esperava , ou }") end
        i = pular(s, i + 1)
    end
end

valor = function(s, i)
    i = pular(s, i)
    local c = s:sub(i, i)
    if c == "{" then return objeto(s, i) end
    if c == "[" then return lista(s, i) end
    if c == '"' then return texto(s, i) end
    if c == "-" or c:match("%d") then return numero(s, i) end
    if s:sub(i, i + 3) == "true" then return true, i + 4 end
    if s:sub(i, i + 4) == "false" then return false, i + 5 end
    if s:sub(i, i + 3) == "null" then return nil, i + 4 end
    erro(s, i, "valor inesperado")
end

--- Decodifica `s`. Devolve a tabela, ou nil e a mensagem de erro.
function json.decode(s)
    if type(s) ~= "string" then return nil, "sem texto" end
    local ok, v, i = pcall(valor, s, 1)
    if not ok then return nil, v end
    if pular(s, i) <= #s then return nil, "sobrou texto depois do JSON" end
    return v
end

return json
