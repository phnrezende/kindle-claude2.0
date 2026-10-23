--[[--
Transforma o JSON que vem do PC no que o painel e o overlay mostram.

Nao depende do KOReader (da para testar com LuaJIT puro). Os textos e as
regras de animacao vieram do server.py do kindle-claude (guithepc, MIT).
]]

local E = {}

E.SEM_SINAL_APOS = 10 * 60      -- sem noticia do PC ha mais que isso: "sem sinal"
E.DIAS = { "dom", "seg", "ter", "qua", "qui", "sex", "sáb" }   -- os.date wday: 1 = domingo

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

local TEXTOS = {
    descansando = { "Fogão desligado", "última ação há %s" },
    esperando = { "Tá pronto!", "esperando você há %s" },
    chamando = { "Te chamando!", "esperando você há %s" },
    prato = { "Prato pronto!", "terminou há %s" },
    cozinhando = { "Cozinhando…", "última ação há %s" },
    sem_sinal = { "Sem sinal do PC", "última notícia há %s" },
}

--- Grupo usado pelo overlay da leitura (so tres estados importam ali).
E.GRUPO = {
    cozinhando = "trabalhando", chamando = "aprovacao", esperando = "pronto",
    prato = "pronto", descansando = "descansando", sem_sinal = "sem_sinal",
}

function E.fmt_tokens(n)
    if n == nil then return "--" end
    if n >= 100000 then
        return (string.format("%.1f", n / 1000000):gsub("%.", ",")) .. " mi"
    end
    if n >= 1000 then
        return string.format("%.0f mil", n / 1000)
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

local function limite(t)
    t = type(t) == "table" and t or {}
    local pct = tonumber(t.pct)
    return { pct = pct, txt = pct and string.format("%.0f%%", pct) or "--", zera = t.zera or "" }
end

--[[--
Calcula a diferenca entre o relogio do Kindle e o do PC no momento da leitura.
`idade` e quantos segundos fazia que o PC tinha enviado (0 no modo local).
]]
function E.desvio(dados, recebido_em, idade)
    local agora_pc = type(dados) == "table" and tonumber(dados.agora)
    if not agora_pc then return 0 end
    return recebido_em - (agora_pc + (idade or 0))
end

--[[--
Monta o que mostrar.

@param dados tabela do JSON do PC (ou nil se nunca chegou nada)
@param agora os.time() do Kindle
@param info { recebido_em, idade, desvio, falhas } da ultima leitura
   recebido_em: os.time() do Kindle na ultima leitura que deu certo
   idade: segundos que o estado ja tinha quando chegou (o relay informa)
   desvio: relogio do Kindle menos o do PC (ver E.desvio)
   falhas: leituras seguidas que falharam
Tudo que depende de hora e calculado no relogio do PC, entao um Kindle com a
hora errada nao vira "sem sinal" nem mostra "ha 3 h" a toa.
]]
function E.interpretar(dados, agora, info)
    info = info or {}
    local d = type(dados) == "table" and dados or {}
    local modo = TEXTOS[d.modo] and d.modo or "descansando"
    local agora_pc = agora - (info.desvio or 0)
    local idade = info.recebido_em and ((info.idade or 0) + (agora - info.recebido_em)) or nil
    local sem_sinal = dados == nil or d.pc_offline
        or (idade and idade > E.SEM_SINAL_APOS)
        or (info.falhas or 0) >= 3
    local ha = (tonumber(d.desde) or 0) > 0 and (agora_pc - tonumber(d.desde)) or nil
    if sem_sinal then
        modo = "sem_sinal"
        ha = idade
    end

    local titulo, linha = TEXTOS[modo][1], TEXTOS[modo][2]
    linha = string.format(linha, ha and E.fmt_ha(ha) or "--")
    local ativos = tonumber(d.ativos) or 0
    if not sem_sinal and ativos > 1 then
        linha = linha .. " · " .. ativos .. " no fogo"
    end

    local ferramenta = (not sem_sinal and d.ferramenta) or ""
    local descricao
    if sem_sinal then
        descricao = (info.falhas or 0) >= 3 and "sem conexão" or "PC desligado?"
    else
        descricao = d.descricao or ""
        if ativos > 1 and (d.projeto or "") ~= "" and ferramenta ~= "" then
            descricao = descricao .. " · " .. d.projeto     -- varios agentes: de qual projeto e
        end
    end

    local antes = {}
    for _, nome in ipairs(type(d.antes) == "table" and d.antes or {}) do
        antes[#antes + 1] = tostring(nome)
    end
    local tok = type(d.tokens) == "table" and d.tokens or {}

    return {
        modo = modo,
        grupo = E.GRUPO[modo],
        titulo = titulo,
        linha = linha,
        ferramenta = ferramenta,
        descricao = descricao,
        antes = #antes > 0 and table.concat(antes, " · ") or "nada ainda",
        sessao = limite(d.sessao),
        semana = limite(d.semana),
        tokens_hoje = E.fmt_tokens(tonumber(tok.hoje)),
        tokens_hora = E.fmt_tokens(tonumber(tok.hora)) .. " na última hora",
        tokens_media = "média " .. E.fmt_tokens(tonumber(tok.media)) .. "/dia",
        rev = d.rev,
    }
end

--- "qui 22/10" e "13:12" com o relogio do Kindle.
function E.data_hora(agora)
    local t = os.date("*t", agora)
    return string.format("%s %02d/%02d", E.DIAS[t.wday], t.day, t.month), string.format("%02d:%02d", t.hour, t.min)
end

return E
