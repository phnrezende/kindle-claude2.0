--[[--
Textos do plugin em portugues (Brasil) e ingles.

O idioma vem da opcao do menu (Claudinho > Idioma). Sem escolha, segue o
idioma do KOReader: portugues se ele estiver em portugues, ingles nos outros.
Nao depende do KOReader (da para testar com LuaJIT puro).

    local L = require("claudinho/textos")
    L.t("titulo_cozinhando")            --> "Cozinhando…" ou "Cooking…"
    L.t("linha_prato", "2 min")         --> "terminou há 2 min" ou "finished 2 min ago"
]]

local L = {
    escolhido = nil,     -- "pt", "en" ou nil (automatico)
}

L.IDIOMAS = { "pt", "en" }

local TEXTOS = {
    pt = {
        -- estados (titulo grande e a linha embaixo)
        titulo_descansando = "Fogão desligado",
        titulo_esperando = "Tá pronto!",
        titulo_chamando = "Te chamando!",
        titulo_prato = "Prato pronto!",
        titulo_cozinhando = "Cozinhando…",
        titulo_sem_sinal = "Sem sinal do PC",
        linha_descansando = "última ação há %s",
        linha_esperando = "esperando você há %s",
        linha_chamando = "esperando você há %s",
        linha_prato = "terminou há %s",
        linha_cozinhando = "última ação há %s",
        linha_sem_sinal = "última notícia há %s",
        varios_agentes = "%d AGENTES",           -- no topo do painel, com varias sessoes

        -- o que esta rodando
        pensando = "pensando…",
        nada_no_fogo = "nada no fogo",
        esperando_resposta = "esperando sua resposta",
        sem_conexao = "sem conexão",
        pc_desligado = "PC desligado?",
        nada_ainda = "nada ainda",

        -- numeros e datas
        decimal = ",",
        milhoes = "%s mi",
        milhares = "%s mil",
        tokens_hora = "%s na última hora",
        tokens_media = "média %s/dia",
        zera_as = "zera às %s",
        zera_dia = "zera %s %s",
        dias = { "seg", "ter", "qua", "qui", "sex", "sáb", "dom" },       -- segunda = 1
        data = function(dia, d, m) return string.format("%s %02d/%02d", dia, d, m) end,

        -- painel
        painel_no_fogo = "NO FOGO AGORA",
        painel_antes = "antes:",
        painel_sessao = "SESSÃO",
        painel_semana = "SEMANA",
        painel_tokens_hoje = "TOKENS HOJE",

        -- avisos
        dica_voltar = "Toque na tela para voltar aos livros",
        overlay_ligado = "Overlay do Claudinho ligado",
        overlay_desligado = "Overlay do Claudinho desligado",
        gesto_painel = "Claudinho: abrir o painel",
        gesto_overlay = "Claudinho: ligar/desligar o overlay",

        -- menu
        menu_abrir = "Abrir o painel",
        menu_overlay = "Overlay na leitura",
        menu_mostrar = "Mostrar o Claudinho no canto da página",
        menu_canto = "Canto",
        canto_superior_direito = "Superior direito",
        canto_superior_esquerdo = "Superior esquerdo",
        canto_inferior_direito = "Inferior direito",
        canto_inferior_esquerdo = "Inferior esquerdo",
        menu_tamanho = "Tamanho",
        tamanho_1 = "Mini",
        tamanho_2 = "Pequeno",
        tamanho_3 = "Médio",
        menu_esconder = "Esconder quando o Claude estiver parado",
        menu_animar_overlay = "Animar (gasta mais bateria)",
        menu_painel = "Painel",
        menu_logo_esquerda = "Logo do Kindle à esquerda",
        menu_logo_direita = "Logo do Kindle à direita",
        menu_animar_mascote = "Animar o mascote",
        menu_acordado = "Não deixar o Kindle dormir com o painel aberto",
        menu_atualizar = "Atualizar a cada",
        menu_lendo = "Lendo",
        menu_com_painel = "Com o painel aberto",
        segundos = "%d segundos",
        minutos = "%d min",
        menu_conexao = "Conexão",
        menu_endereco = "Endereço: %s",
        vazio = "(vazio)",
        endereco_titulo = "Endereço do estado",
        endereco_ajuda = "http://IP-DO-PC:8787/estado.json (PC e Kindle na mesma rede Wi-Fi)",
        menu_token = "Token",
        token_ajuda = "O mesmo que está em pc/config.json (\"token\").",
        menu_testar = "Testar a conexão agora",
        menu_voltar_config = "Voltar ao config.lua do setup",
        cancelar = "Cancelar",
        salvar = "Salvar",
        buscando = "Buscando o estado…",
        conectado = "Conectado.\n\nClaude: %s\n%s",
        nao_conectou = "Não consegui ler o estado.\n\n%s\n\nURL: %s",
        erro_desconhecido = "erro desconhecido",
        menu_idioma = "Idioma: %s",
        idioma_auto = "Automático (idioma do KOReader)",
        menu_sobre = "Sobre",
        sobre = "Claudinho %s\n\nO status do Claude Code no seu Kindle.\n\n"
            .. "Painel e Claudinho chef: kindle-claude, de guithepc (MIT).\n"
            .. "Fontes Inter Tight e JetBrains Mono (OFL).",

        -- erros da busca
        erro_sem_url = "sem URL configurada",
        erro_wifi = "Wi-Fi desligado",
        erro_token = "token recusado pelo PC",
        erro_resposta = "resposta inválida: %s",
        erro_http = "HTTP %s",
        erro_sem_resposta = "sem resposta",
        erro_tempo = "tempo esgotado",
        erro_subprocesso = "subprocesso sem resposta",
        erro_ilegivel = "resposta ilegível",
        erro_leitura = "falha ao ler a resposta: %s",
    },

    en = {
        titulo_descansando = "Stove's off",
        titulo_esperando = "All done!",
        titulo_chamando = "Calling you!",
        titulo_prato = "Order up!",
        titulo_cozinhando = "Cooking…",
        titulo_sem_sinal = "No PC signal",
        linha_descansando = "last action %s ago",
        linha_esperando = "waiting on you for %s",
        linha_chamando = "waiting on you for %s",
        linha_prato = "finished %s ago",
        linha_cozinhando = "last action %s ago",
        linha_sem_sinal = "last heard %s ago",
        varios_agentes = "%d AGENTS",

        pensando = "thinking…",
        nada_no_fogo = "nothing cooking",
        esperando_resposta = "waiting for your answer",
        sem_conexao = "no connection",
        pc_desligado = "PC off?",
        nada_ainda = "nothing yet",

        decimal = ".",
        milhoes = "%sM",
        milhares = "%sK",
        tokens_hora = "%s in the last hour",
        tokens_media = "avg %s/day",
        zera_as = "resets at %s",
        zera_dia = "resets %s %s",
        dias = { "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun" },
        meses = { "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec" },
        data = function(dia, d, m, meses) return string.format("%s %s %d", dia, meses[m], d) end,

        painel_no_fogo = "ON THE STOVE",
        painel_antes = "before:",
        painel_sessao = "SESSION",
        painel_semana = "WEEK",
        painel_tokens_hoje = "TOKENS TODAY",

        dica_voltar = "Tap the screen to go back to your books",
        overlay_ligado = "Claudinho overlay on",
        overlay_desligado = "Claudinho overlay off",
        gesto_painel = "Claudinho: open the panel",
        gesto_overlay = "Claudinho: toggle the overlay",

        menu_abrir = "Open the panel",
        menu_overlay = "Reading overlay",
        menu_mostrar = "Show Claudinho in the page corner",
        menu_canto = "Corner",
        canto_superior_direito = "Top right",
        canto_superior_esquerdo = "Top left",
        canto_inferior_direito = "Bottom right",
        canto_inferior_esquerdo = "Bottom left",
        menu_tamanho = "Size",
        tamanho_1 = "Mini",
        tamanho_2 = "Small",
        tamanho_3 = "Medium",
        menu_esconder = "Hide when Claude is idle",
        menu_animar_overlay = "Animate (uses more battery)",
        menu_painel = "Panel",
        menu_logo_esquerda = "Kindle logo on the left",
        menu_logo_direita = "Kindle logo on the right",
        menu_animar_mascote = "Animate the mascot",
        menu_acordado = "Keep the Kindle awake while the panel is open",
        menu_atualizar = "Refresh every",
        menu_lendo = "While reading",
        menu_com_painel = "With the panel open",
        segundos = "%d seconds",
        minutos = "%d min",
        menu_conexao = "Connection",
        menu_endereco = "Address: %s",
        vazio = "(empty)",
        endereco_titulo = "State address",
        endereco_ajuda = "http://PC-IP:8787/estado.json (PC and Kindle on the same Wi-Fi)",
        menu_token = "Token",
        token_ajuda = "The same one as in pc/config.json (\"token\").",
        menu_testar = "Test the connection now",
        menu_voltar_config = "Go back to the setup's config.lua",
        cancelar = "Cancel",
        salvar = "Save",
        buscando = "Fetching the state…",
        conectado = "Connected.\n\nClaude: %s\n%s",
        nao_conectou = "Couldn't read the state.\n\n%s\n\nURL: %s",
        erro_desconhecido = "unknown error",
        menu_idioma = "Language: %s",
        idioma_auto = "Automatic (KOReader's language)",
        menu_sobre = "About",
        sobre = "Claudinho %s\n\nClaude Code's status on your Kindle.\n\n"
            .. "Panel and chef Claudinho: kindle-claude, by guithepc (MIT).\n"
            .. "Inter Tight and JetBrains Mono fonts (OFL).",

        erro_sem_url = "no URL set",
        erro_wifi = "Wi-Fi is off",
        erro_token = "token rejected by the PC",
        erro_resposta = "invalid response: %s",
        erro_http = "HTTP %s",
        erro_sem_resposta = "no response",
        erro_tempo = "timed out",
        erro_subprocesso = "the subprocess gave no answer",
        erro_ilegivel = "unreadable response",
        erro_leitura = "failed to read the response: %s",
    },
}

-- o nome de cada idioma, escrito nele mesmo (aparece igual nos dois menus)
L.NOMES = { pt = "Português (Brasil)", en = "English" }

--- Idioma do KOReader ("pt_BR", "en"...) reduzido a "pt" ou "en".
function L.do_koreader()
    local G = rawget(_G, "G_reader_settings")
    local ok, lang = pcall(function() return G and G:readSetting("language") end)
    if ok and type(lang) == "string" and lang:lower():match("^pt") then return "pt" end
    return "en"
end

--- O idioma em uso agora: "pt" ou "en".
function L.atual()
    return L.escolhido or L.do_koreader()
end

--- Escolhe o idioma: "pt", "en" ou nil (segue o KOReader).
function L.escolher(idioma)
    L.escolhido = TEXTOS[idioma] and idioma or nil
end

--- O texto `chave` no idioma atual, formatado com `...` se houver.
function L.t(chave, ...)
    local tab = TEXTOS[L.atual()]
    local s = tab[chave]
    if s == nil then s = TEXTOS.pt[chave] end
    if s == nil then return chave end
    if select("#", ...) > 0 then return string.format(s, ...) end
    return s
end

--- Dia da semana abreviado; 1 = segunda ... 7 = domingo.
function L.dia(n)
    local dias = TEXTOS[L.atual()].dias
    return dias[tonumber(n)] or ""
end

--- "qui 22/10" ou "Thu Oct 22". `wday` como no os.date (1 = domingo).
function L.data(wday, dia, mes)
    local tab = TEXTOS[L.atual()]
    local iso = (wday + 5) % 7 + 1                  -- 1 = domingo -> 7, 2 = segunda -> 1
    return tab.data(tab.dias[iso], dia, mes, tab.meses)
end

-- exposto para o teste conferir que os dois idiomas tem as mesmas chaves
L._TEXTOS = TEXTOS

return L
