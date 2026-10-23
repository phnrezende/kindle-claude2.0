--[[--
Transforma o JSON que vem do PC no que o painel e o overlay mostram.

Nao depende do KOReader (da para testar com LuaJIT puro). Os textos e as
regras de animacao vieram do server.py do kindle-claude (guithepc, MIT).
O PC manda so dados (modo, nomes, numeros, horas); as frases saem daqui, no
idioma escolhido (claudinho/textos.lua).
]]

local L = require("claudinho/textos")

local E = {}

E.SEM_SINAL_APOS = 10 * 60      -- sem noticia do PC ha mais que isso: "sem sinal"

-- segundos por quadro de cada animacao
E.ATRASO = {
    cozinhando = 1.5, prato = 1.5, esperando = 1.5, chamando = 1.0, descansando = 4.0, sem_sinal = 4.0,
}
-- blocos sorteados enquanto o Claude trabalha (cada bloco = quadro 1, quadro 2)
E.COZINHA = { "sopa", "cebola", "tempero", "frigideira" }
E.BLOCOS = 10

local ANIMACAO = {
    cozinhando = "sopa", prato = "prato", esperando = "esperando",
    chamando = "esperando", descansando = "descansando", sem_sinal = "descansando",
}

--- Grupo usado pelo overlay da leitura (so tres estados importam ali).
E.GRUPO = {
    cozinhando = "trabalhando", chamando = "aprovacao", esperando = "pronto",
    prato = "pronto", descansando = "descansando", sem_sinal = "sem_sinal",
}

function E.fmt_tokens(n)
    if n == nil then return "--" end
    if n >= 100000 then
        local s = string.format("%.1f", n / 1000000):gsub("%.", L.t("decimal"))
        return L.t("milhoes", s)
    end
    if n >= 1000 then
        return L.t("milhares", string.format("%.0f", n / 1000))
    end
    return tostring(math.floor(n))
end

function E.fmt_ha(segundos)
    local s = math.floor(math.max(0, segundos or 0))
    if s < 60 then return s .. "s" end
    if s < 3600 then return math.floor(s / 60) .. " min" end
    local min = math.floor(s / 60)
    local h, m = math.floor(min / 60), min % 60
    if m == 0 or h >= 3 then return h .. " h" end
    return h .. " h " .. m .. " min"
end

--- Primeiro quadro da animacao do modo (o que fica parado no overlay).
function E.quadro_parado(modo)
    return (ANIMACAO[modo] or "descansando") .. "_1"
end

--- Sequencia de quadros ate a proxima leitura. `sorteio(n)` devolve 1..n.
function E.sequencia(modo, sorteio)
    if modo ~= "cozinhando" then
        local a = ANIMACAO[modo] or "descansando"
        return { a .. "_1", a .. "_2" }
    end
    sorteio = sorteio or math.random
    local seq, ultimo = {}, nil
    for _ = 1, E.BLOCOS do
        local opcoes = {}
        for _, b in ipairs(E.COZINHA) do
            if b ~= ultimo then opcoes[#opcoes + 1] = b end
        end
        local b = opcoes[sorteio(#opcoes)]
        seq[#seq + 1] = b .. "_1"
        seq[#seq + 1] = b .. "_2"
        ultimo = b
    end
    return seq
end

--- Limite de uso: { pct = 11, hora = "15:00" } e, na semana, dia = 1..7 (segunda = 1).
local function limite(t)
    t = type(t) == "table" and t or {}
    local pct = tonumber(t.pct)
    local zera = ""
    if type(t.hora) == "string" and t.hora ~= "" then
        local dia = tonumber(t.dia)
        zera = dia and L.t("zera_dia", L.dia(dia), t.hora) or L.t("zera_as", t.hora)
    elseif type(t.zera) == "string" then
        zera = t.zera                -- agente antigo (v1): ja vinha escrito em portugues
    end
    return { pct = pct, txt = pct and string.format("%.0f%%", pct) or "--", zera = zera }
end

--- So texto (ou numero) vira texto; o resto (tabela, booleano, nil) vira "".
--- Este codigo roda a cada pagina do livro, entao nada aqui pode dar erro.
local function texto(v)
    if type(v) == "string" then return v end
    if type(v) == "number" then return tostring(v) end
    return ""
end

--- O que aparece na barra quando nao ha ferramenta rodando.
local function sem_ferramenta(modo)
    if modo == "cozinhando" then return L.t("pensando") end
    if modo == "chamando" then return L.t("esperando_resposta") end
    return L.t("nada_no_fogo")
end

-- frases que o agente antigo (v1) mandava prontas: viram o texto do idioma atual
local ANTIGOS = { ["pensando…"] = true, ["nada no fogo"] = true, ["esperando sua resposta"] = true }

--[[--
Calcula a diferenca entre o relogio do Kindle e o do PC no momento da leitura
(o PC monta o estado na hora em que responde).
]]
function E.desvio(dados, recebido_em)
    local agora_pc = type(dados) == "table" and tonumber(dados.agora)
    if not agora_pc then return 0 end
    return recebido_em - agora_pc
end

--[[--
Monta o que mostrar.

@param dados tabela do JSON do PC (ou nil se nunca chegou nada)
@param agora os.time() do Kindle
@param info { recebido_em, desvio, falhas, dormiu } da ultima leitura
   recebido_em: os.time() do Kindle na ultima leitura que deu certo
   desvio: relogio do Kindle menos o do PC (ver E.desvio)
   falhas: leituras seguidas que falharam
   dormiu: segundos que o Kindle passou dormindo desde essa leitura. Nao contam
     para o "sem sinal": ao acordar, a pagina mostra o ultimo estado ate a
     proxima busca, em vez de piscar "sem sinal" a cada despertar.
O "ha X min" e calculado no relogio do PC, entao um Kindle com a hora errada
nao mostra "ha 3 h" a toa.
]]
function E.interpretar(dados, agora, info)
    info = info or {}
    local d = type(dados) == "table" and dados or {}
    local modo = E.GRUPO[d.modo] and d.modo ~= "sem_sinal" and d.modo or "descansando"
    local agora_pc = agora - (info.desvio or 0)
    local idade = info.recebido_em and (agora - info.recebido_em) or nil
    local acordado = idade and (idade - math.max(0, tonumber(info.dormiu) or 0)) or nil
    local sem_sinal = dados == nil
        or (acordado and acordado > E.SEM_SINAL_APOS)
        or (info.falhas or 0) >= 3
    local ha = (tonumber(d.desde) or 0) > 0 and (agora_pc - tonumber(d.desde)) or nil
    if sem_sinal then
        modo = "sem_sinal"
        ha = idade
    end

    local titulo = L.t("titulo_" .. modo)
    local linha = L.t("linha_" .. modo, ha and E.fmt_ha(ha) or "--")
    local ativos = tonumber(d.ativos) or 0
    -- com varias sessoes, o painel mostra "3 AGENTES" no topo (na linha nao cabia)
    local agentes = (not sem_sinal and ativos > 1) and L.t("varios_agentes", ativos) or ""

    local ferramenta = sem_sinal and "" or texto(d.ferramenta)
    local descricao
    if sem_sinal then
        descricao = (info.falhas or 0) >= 3 and L.t("sem_conexao") or L.t("pc_desligado")
    else
        descricao = texto(d.descricao)
        if ferramenta == "" and (descricao == "" or ANTIGOS[descricao]) then
            descricao = sem_ferramenta(modo)
        end
        local projeto = texto(d.projeto)
        if ativos > 1 and projeto ~= "" and ferramenta ~= "" then
            descricao = descricao .. " · " .. projeto       -- varios agentes: de qual projeto e
        end
    end

    local antes = {}
    for _, nome in ipairs(type(d.antes) == "table" and d.antes or {}) do
        if texto(nome) ~= "" then antes[#antes + 1] = texto(nome) end
    end
    local tok = type(d.tokens) == "table" and d.tokens or {}

    return {
        modo = modo,
        grupo = E.GRUPO[modo],
        titulo = titulo,
        linha = linha,
        agentes = agentes,
        ferramenta = ferramenta,
        descricao = descricao,
        antes = #antes > 0 and table.concat(antes, " · ") or L.t("nada_ainda"),
        sessao = limite(d.sessao),
        semana = limite(d.semana),
        tokens_hoje = E.fmt_tokens(tonumber(tok.hoje)),
        tokens_hora = L.t("tokens_hora", E.fmt_tokens(tonumber(tok.hora))),
        tokens_media = L.t("tokens_media", E.fmt_tokens(tonumber(tok.media))),
        rev = texto(d.rev),
        idioma = L.atual(),
    }
end

local GRUPOS = { trabalhando = true, aprovacao = true, pronto = true, descansando = true, sem_sinal = true }

--- Texto curto para a barra de status do KOReader (modo "na barra de status"),
--- ou nil para nao mostrar nada. `so_ativo`: esconde quando o Claude esta parado.
function E.texto_barra(v, so_ativo)
    local g = type(v) == "table" and GRUPOS[v.grupo] and v.grupo or "sem_sinal"
    if so_ativo and (g == "descansando" or g == "sem_sinal") then return nil end
    return L.t("barra_" .. g)
end

--- "qui 22/10" (ou "Thu Oct 22") e "13:12" com o relogio do Kindle.
function E.data_hora(agora)
    local t = os.date("*t", agora)
    return L.data(t.wday, t.day, t.month), string.format("%02d:%02d", t.hour, t.min)
end

return E
