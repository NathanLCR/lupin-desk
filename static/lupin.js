/**
 * Rosto do Lupin em camadas (/static/lupin.js)
 *
 * Desenha o husky a partir dos SVGs em /static/lupin/camadas/ e da tabela
 * /static/lupin/expressoes.json (mesma tabela que o Corpo ESP32/LVGL usa).
 * Expõe a API pública em window.LupinFace.
 */
(function (global) {
  'use strict';

  const BASE = '/static/lupin/';
  const TABELA_URL = BASE + 'expressoes.json';
  const LARGURA = 480;
  const ALTURA = 320;

  const SUPPORTED_STATES = Object.freeze(['idle', 'listening', 'thinking', 'speaking', 'error']);
  const SUPPORTED_EMOTIONS = Object.freeze([
    'neutral', 'happy', 'excited', 'curious', 'skeptical', 'surprised',
    'sad', 'wink', 'love', 'sleepy', 'angry', 'dizzy',
  ]);
  const SUPPORTED_ACCESSORIES = Object.freeze(['none', 'headphones', 'pomodoro']);

  // Olhos que fecham ao piscar. Os demais (fechado, feliz, x...) já são "fechados".
  const OLHOS_QUE_PISCAM = Object.freeze(['aberto', 'brilho', 'surpreso', 'bravo', 'triste', 'cetico']);
  const IDLE_SLEEP_TIMEOUT_MS = 90000;
  const OLHAR_MANUAL_MS = 2500;
  const BLINK_MS = 130;

  function clamp(value, min, max) {
    if (typeof value !== 'number' || Number.isNaN(value)) return min;
    return Math.min(max, Math.max(min, value));
  }

  function lerp(current, target, factor) {
    return current + (target - current) * factor;
  }

  function nowMs() {
    return typeof performance !== 'undefined' && performance.now ? performance.now() : Date.now();
  }

  /**
   * Resolve a variante de cada camada. Pura: a ordem de precedência é
   * padrão < expressão < estado < piscada < fala.
   */
  function resolverCamadas(tabela, entrada) {
    const camadas = Object.assign({}, tabela.padrao);
    const expressao = tabela.expressoes[entrada.emocao] || {};
    const estado = tabela.estados[entrada.estado] || {};
    let inclinacao = 0;
    let olhar = null;
    [expressao, estado].forEach((origem) => {
      Object.keys(origem).forEach((chave) => {
        if (chave === 'inclinacao') inclinacao = origem[chave];
        else if (chave === 'olhar') olhar = origem[chave];
        else if (chave === 'falando') return;
        else if (tabela.camadas[chave]) camadas[chave] = origem[chave];
      });
    });
    if (entrada.piscando && OLHOS_QUE_PISCAM.includes(camadas.olhos)) {
      camadas.olhos = 'fechado';
    }
    if (estado.falando) {
      const nivel = entrada.nivelAudio;
      camadas.boca = nivel < 0.12 ? 'fechada' : nivel < 0.4 ? 'meio-aberta' : 'aberta';
    }
    return { camadas, inclinacao, olhar };
  }

  const internal = {
    container: null,
    root: null,
    stage: null,
    respira: null,
    grupoCabeca: null,
    corpo: null,
    imgs: {},
    camadaEl: {},
    visivel: {},
    tabela: null,
    carregando: false,
    estado: 'idle',
    emocao: 'neutral',
    emocaoTimer: null,
    nivelAudio: 0,
    piscando: false,
    proximaPiscada: 0,
    fimPiscada: 0,
    olharX: 0,
    olharY: 0,
    alvoX: 0,
    alvoY: 0,
    olharManualAte: 0,
    proximoOlhar: 0,
    inclinacao: 0,
    inclinacaoAtual: 0,
    ultimaInteracao: 0,
    sonolento: false,
    musica: false,
    acessorio: 'none',
    compacto: false,
    cliques: [],
    truqueTimers: [],
    truqueAtivo: null,
    rafId: null,
    escala: 0,
    motionQuery: null,
    motionListener: null,
    reduzirMovimento: false,
  };

  function shouldReduceMotion() {
    return internal.reduzirMovimento;
  }

  function limparPreferenciaMovimento() {
    if (internal.motionQuery && internal.motionListener) {
      if (typeof internal.motionQuery.removeEventListener === 'function') {
        internal.motionQuery.removeEventListener('change', internal.motionListener);
      }
    }
    internal.motionQuery = null;
    internal.motionListener = null;
  }

  function ligarPreferenciaMovimento() {
    limparPreferenciaMovimento();
    if (typeof global.matchMedia !== 'function') {
      internal.reduzirMovimento = false;
      return;
    }
    const query = global.matchMedia('(prefers-reduced-motion: reduce)');
    internal.reduzirMovimento = Boolean(query && query.matches);
    if (query && typeof query.addEventListener === 'function') {
      internal.motionListener = (event) => {
        internal.reduzirMovimento = Boolean(event.matches);
        if (internal.reduzirMovimento) assentar();
        aplicar();
      };
      query.addEventListener('change', internal.motionListener);
      internal.motionQuery = query;
    }
  }

  // Com movimento reduzido, tudo para na pose estática da expressão atual.
  function assentar() {
    internal.piscando = false;
    internal.olharX = 0;
    internal.olharY = 0;
    internal.alvoX = 0;
    internal.alvoY = 0;
    internal.inclinacaoAtual = internal.inclinacao;
    if (internal.respira) internal.respira.style.transform = '';
    transformarOlhar();
  }

  function registrarInteracao(ts) {
    internal.ultimaInteracao = typeof ts === 'number' ? ts : nowMs();
    internal.sonolento = false;
  }

  function criar(tag, classe) {
    const el = global.document.createElement(tag);
    if (classe) el.className = classe;
    return el;
  }

  function construirDom(container) {
    container.textContent = '';
    const root = criar('div', 'lupin-root');
    root.setAttribute('role', 'img');
    root.setAttribute('aria-label', 'Lupin, o husky de estimação');
    const stage = criar('div', 'lupin-stage');
    const respira = criar('div', 'lupin-respira');
    stage.appendChild(respira);
    root.appendChild(stage);
    container.appendChild(root);
    internal.container = container;
    internal.root = root;
    internal.stage = stage;
    internal.respira = respira;
    internal.grupoCabeca = null;
    internal.corpo = null;
    internal.imgs = {};
    internal.camadaEl = {};
    internal.visivel = {};
  }

  function construirCamadas() {
    const tabela = internal.tabela;
    const respira = internal.respira;
    respira.textContent = '';
    internal.imgs = {};
    internal.camadaEl = {};
    internal.visivel = {};
    const dentroDaCabeca = new Set(tabela.grupoCabeca);
    const grupo = criar('div', 'lupin-grupo-cabeca');
    internal.grupoCabeca = grupo;
    let grupoAnexado = false;
    tabela.ordemCamadas.forEach((nome) => {
      const camada = criar('div', 'lupin-camada lupin-camada-' + nome);
      camada.dataset.camada = nome;
      internal.imgs[nome] = {};
      internal.camadaEl[nome] = camada;
      tabela.camadas[nome].forEach((variante) => {
        const img = criar('img', 'lupin-variante');
        img.setAttribute('src', BASE + 'camadas/' + nome + '/' + variante + '.svg');
        img.setAttribute('alt', '');
        img.setAttribute('draggable', 'false');
        img.hidden = true;
        camada.appendChild(img);
        internal.imgs[nome][variante] = img;
      });
      if (dentroDaCabeca.has(nome)) {
        grupo.appendChild(camada);
        if (!grupoAnexado) {
          respira.appendChild(grupo);
          grupoAnexado = true;
        }
      } else {
        respira.appendChild(camada);
      }
    });
    const corpo = criar('img', 'lupin-corpo');
    corpo.setAttribute('alt', '');
    corpo.setAttribute('draggable', 'false');
    corpo.hidden = true;
    internal.stage.appendChild(corpo);
    internal.corpo = corpo;
  }

  function carregarTabela() {
    if (internal.carregando || internal.tabela || typeof global.fetch !== 'function') return;
    internal.carregando = true;
    Promise.resolve(global.fetch(TABELA_URL))
      .then((resposta) => {
        if (!resposta || resposta.ok === false) throw new Error('HTTP ' + (resposta && resposta.status));
        return resposta.json();
      })
      .then((tabela) => {
        internal.tabela = tabela;
        internal.carregando = false;
        if (internal.stage) {
          construirCamadas();
          aplicar();
        }
      })
      .catch((erro) => {
        internal.carregando = false;
        if (typeof console !== 'undefined' && console.warn) {
          console.warn('[LupinFace] Não consegui carregar a tabela de expressões:', erro);
        }
      });
  }

  function emocaoEfetiva() {
    if (internal.sonolento && internal.emocao === 'neutral') return 'sleepy';
    return internal.emocao;
  }

  function entradaAtual() {
    return {
      emocao: emocaoEfetiva(),
      estado: internal.estado,
      piscando: internal.piscando,
      nivelAudio: internal.nivelAudio,
    };
  }

  function transformarOlhar() {
    if (!internal.tabela || !internal.camadaEl.olhos) return;
    const dx = (internal.olharX * 9).toFixed(2);
    const dy = (internal.olharY * 6).toFixed(2);
    const valor = 'translate(' + dx + 'px, ' + dy + 'px)';
    ['olhos', 'sobrancelhas'].forEach((nome) => {
      const camada = internal.camadaEl[nome];
      if (camada) camada.style.transform = valor;
    });
  }

  function transformarCabeca() {
    if (!internal.grupoCabeca) return;
    const graus = internal.inclinacaoAtual.toFixed(2);
    const px = (internal.olharX * 3).toFixed(2);
    internal.grupoCabeca.style.transform = 'translate(' + px + 'px, 0) rotate(' + graus + 'deg)';
  }

  function atualizarAtributos() {
    const root = internal.root;
    if (!root) return;
    root.dataset.state = internal.estado;
    root.dataset.emotion = emocaoEfetiva();
    root.dataset.compact = internal.compacto ? 'true' : 'false';
    root.dataset.accessory = internal.acessorio;
    root.classList.toggle('lupin-compacto', internal.compacto);
    root.classList.toggle('lupin-falando', internal.estado === 'speaking');
  }

  // Aplica o estado lógico atual às camadas visíveis.
  function aplicar() {
    atualizarAtributos();
    if (!internal.tabela || !internal.stage || !internal.grupoCabeca) return;
    const resolvido = resolverCamadas(internal.tabela, entradaAtual());
    Object.keys(resolvido.camadas).forEach((nome) => {
      const escolhida = resolvido.camadas[nome];
      if (internal.visivel[nome] === escolhida) return;
      const variantes = internal.imgs[nome];
      if (!variantes || !variantes[escolhida]) return;
      if (internal.visivel[nome] && variantes[internal.visivel[nome]]) {
        variantes[internal.visivel[nome]].hidden = true;
      }
      variantes[escolhida].hidden = false;
      internal.visivel[nome] = escolhida;
    });
    internal.inclinacao = resolvido.inclinacao || 0;
    if (resolvido.olhar && Date.now() > internal.olharManualAte) {
      internal.alvoX = resolvido.olhar.x;
      internal.alvoY = resolvido.olhar.y;
    }
    if (shouldReduceMotion()) {
      internal.inclinacaoAtual = internal.inclinacao;
      transformarCabeca();
    }
  }

  function ajustarEscala() {
    if (!internal.root || !internal.stage) return;
    const w = internal.root.clientWidth || LARGURA;
    const h = internal.root.clientHeight || ALTURA;
    const k = Math.min(w / LARGURA, h / ALTURA);
    if (Math.abs(k - internal.escala) < 0.001) return;
    internal.escala = k;
    internal.stage.style.transform = 'translate(-50%, -50%) scale(' + k.toFixed(4) + ')';
  }

  function agendarPiscada(ts) {
    internal.proximaPiscada = ts + 2600 + Math.random() * 3600;
  }

  function step(ts) {
    internal.rafId = null;
    if (!internal.root) return;
    ajustarEscala();
    const reduzir = shouldReduceMotion();

    if (!reduzir) {
      if (ts >= internal.proximaPiscada && !internal.piscando) {
        internal.piscando = true;
        internal.fimPiscada = ts + BLINK_MS;
        agendarPiscada(ts);
        aplicar();
      } else if (internal.piscando && ts >= internal.fimPiscada) {
        internal.piscando = false;
        aplicar();
      }

      // Olhar em volta quando ninguém está dirigindo o olhar.
      if (Date.now() > internal.olharManualAte && internal.estado !== 'thinking') {
        if (ts >= internal.proximoOlhar) {
          internal.alvoX = (Math.random() - 0.5) * 1.0;
          internal.alvoY = (Math.random() - 0.5) * 0.5;
          internal.proximoOlhar = ts + 3000 + Math.random() * 4000;
        }
      }
      internal.olharX = lerp(internal.olharX, internal.alvoX, 0.12);
      internal.olharY = lerp(internal.olharY, internal.alvoY, 0.12);
      transformarOlhar();

      let alvoInclinacao = internal.inclinacao;
      if (internal.musica) alvoInclinacao += Math.sin(ts / 260) * 2.2;
      internal.inclinacaoAtual = lerp(internal.inclinacaoAtual, alvoInclinacao, 0.14);
      transformarCabeca();

      const respiracao = 1 + 0.012 * Math.sin(ts / 900);
      internal.respira.style.transform = 'scale(' + respiracao.toFixed(4) + ')';

      if (internal.estado === 'idle' && !internal.sonolento && ts - internal.ultimaInteracao > IDLE_SLEEP_TIMEOUT_MS) {
        internal.sonolento = true;
        aplicar();
      }
    }

    if (internal.estado === 'speaking') {
      aplicar();
      const colar = internal.camadaEl.colar;
      if (colar) {
        const brilho = 3 + internal.nivelAudio * 12;
        colar.style.filter = 'drop-shadow(0 0 ' + brilho.toFixed(1) + 'px #22d3ee)';
      }
    }

    if (typeof global.requestAnimationFrame === 'function') {
      internal.rafId = global.requestAnimationFrame(step);
    }
  }

  function limparTruque() {
    internal.truqueTimers.forEach((id) => clearTimeout(id));
    internal.truqueTimers = [];
    internal.truqueAtivo = null;
    if (internal.corpo) internal.corpo.hidden = true;
    if (internal.root) internal.root.classList.remove('lupin-corpo-inteiro');
    if (internal.stage) {
      const efeitos = internal.stage.efeitos || [];
      efeitos.forEach((el) => el.parentNode && el.parentNode.removeChild(el));
      internal.stage.efeitos = [];
    }
  }

  function agendar(fn, ms) {
    const id = setTimeout(fn, ms);
    internal.truqueTimers.push(id);
    return id;
  }

  function lancarEfeito(tipo, quantidade) {
    if (!internal.stage || shouldReduceMotion()) return;
    internal.stage.efeitos = internal.stage.efeitos || [];
    for (let i = 0; i < quantidade; i += 1) {
      const el = criar('i', 'lupin-efeito lupin-efeito-' + tipo);
      el.style.setProperty('--i', String(i));
      el.style.setProperty('--x', String(Math.round((i / Math.max(1, quantidade - 1)) * 100)));
      internal.stage.appendChild(el);
      internal.stage.efeitos.push(el);
    }
  }

  const LupinFace = {
    init(containerEl) {
      let container = containerEl;
      if (typeof container === 'string' && global.document && global.document.querySelector) {
        container = global.document.querySelector(container);
      }
      if (!container) {
        throw new Error('LupinFace.init: containerEl inválido ou não encontrado.');
      }
      if (internal.rafId !== null && typeof global.cancelAnimationFrame === 'function') {
        global.cancelAnimationFrame(internal.rafId);
        internal.rafId = null;
      }
      limparTruque();
      construirDom(container);
      ligarPreferenciaMovimento();
      internal.escala = 0;
      const ts = nowMs();
      registrarInteracao(ts);
      agendarPiscada(ts);
      internal.proximoOlhar = ts + 2500;
      if (internal.tabela) construirCamadas();
      else carregarTabela();
      aplicar();
      ajustarEscala();
      if (typeof global.requestAnimationFrame === 'function') {
        internal.rafId = global.requestAnimationFrame(step);
      }
      return LupinFace;
    },

    setState(state) {
      if (!SUPPORTED_STATES.includes(state)) {
        if (typeof console !== 'undefined' && console.warn) {
          console.warn('[LupinFace] Estado desconhecido ignorado: ' + state);
        }
        return internal.estado;
      }
      internal.estado = state;
      if (state !== 'speaking') internal.nivelAudio = 0;
      if (state !== 'speaking' && internal.camadaEl.colar) {
        internal.camadaEl.colar.style.filter = '';
      }
      registrarInteracao();
      aplicar();
      return internal.estado;
    },

    setEmotion(emotion, opts) {
      if (!SUPPORTED_EMOTIONS.includes(emotion)) {
        if (typeof console !== 'undefined' && console.warn) {
          console.warn('[LupinFace] Emoção desconhecida ignorada: ' + emotion);
        }
        return internal.emocao;
      }
      if (internal.emocaoTimer !== null) {
        clearTimeout(internal.emocaoTimer);
        internal.emocaoTimer = null;
      }
      internal.emocao = emotion;
      registrarInteracao();
      if (opts && typeof opts.durationMs === 'number' && opts.durationMs > 0) {
        internal.emocaoTimer = setTimeout(() => {
          internal.emocaoTimer = null;
          internal.emocao = 'neutral';
          aplicar();
        }, opts.durationMs);
      }
      aplicar();
      return internal.emocao;
    },

    lookAt(x, y) {
      internal.alvoX = clamp(Number(x), -1, 1);
      internal.alvoY = clamp(Number(y), -1, 1);
      internal.olharManualAte = Date.now() + OLHAR_MANUAL_MS;
      registrarInteracao();
      if (shouldReduceMotion()) {
        internal.olharX = 0;
        internal.olharY = 0;
      }
    },

    blink() {
      if (shouldReduceMotion()) return;
      internal.piscando = true;
      internal.fimPiscada = nowMs() + BLINK_MS;
      aplicar();
    },

    setAudioLevel(level) {
      internal.nivelAudio = clamp(Number(level), 0, 1);
    },

    getState() {
      return internal.estado;
    },

    getEmotion() {
      return internal.emocao;
    },

    getSupportedEmotions() {
      return SUPPORTED_EMOTIONS.slice();
    },

    getSupportedStates() {
      return SUPPORTED_STATES.slice();
    },

    getTricks() {
      return internal.tabela ? Object.keys(internal.tabela.truques) : [];
    },

    /**
     * Toque direto. 'pet' (carinho) deixa Lupin feliz; 'poke' (cutucada)
     * assusta, e cutucadas repetidas irritam.
     */
    reactToTouch(kind, nx, ny) {
      registrarInteracao();
      const audio = global.EmoAudio;
      if (kind === 'pet') {
        LupinFace.setEmotion('happy', { durationMs: 2400 });
        LupinFace.lookAt(nx, ny);
        if (audio && typeof audio.purr === 'function') audio.purr(true);
        return;
      }
      if (kind === 'poke') {
        const agora = Date.now();
        internal.cliques = internal.cliques.filter((t) => agora - t < 3000);
        internal.cliques.push(agora);
        const n = internal.cliques.length;
        if (n >= 3) {
          LupinFace.setEmotion('angry', { durationMs: 3600 });
          if (audio && typeof audio.chirp === 'function') audio.chirp('angry');
        } else if (n === 2) {
          LupinFace.setEmotion('skeptical', { durationMs: 3000 });
          if (audio && typeof audio.chirp === 'function') audio.chirp('skeptical');
        } else {
          LupinFace.setEmotion('surprised', { durationMs: 900 });
          if (audio && typeof audio.click === 'function') audio.click();
        }
        LupinFace.lookAt(nx, ny);
      }
    },

    // Acessórios ficam registrados; a arte deles entra junto da arte final.
    setAccessory(name) {
      if (!SUPPORTED_ACCESSORIES.includes(name)) return internal.acessorio;
      internal.acessorio = name;
      atualizarAtributos();
      return internal.acessorio;
    },

    setCompactMode(active) {
      internal.compacto = Boolean(active);
      atualizarAtributos();
    },

    setMusicPlaying(active) {
      internal.musica = Boolean(active);
      if (!internal.musica && !shouldReduceMotion()) internal.inclinacaoAtual = internal.inclinacao;
    },

    getHitboxRect() {
      if (!internal.stage || typeof internal.stage.getBoundingClientRect !== 'function') return null;
      return internal.stage.getBoundingClientRect();
    },

    /**
     * Truques vêm da tabela: 'corpo' troca o busto por quadros de corpo
     * inteiro durante o Truque; 'busto' fica no busto com expressão e efeito.
     */
    playTrick(trickId) {
      const id = typeof trickId === 'string' ? trickId.toLowerCase() : '';
      const truque = internal.tabela && internal.tabela.truques[id];
      if (!truque) return false;
      registrarInteracao();
      limparTruque();
      internal.truqueAtivo = id;

      if (truque.modo === 'busto') {
        LupinFace.setEmotion(truque.expressao, { durationMs: truque.duracaoMs });
        const quantidade = { notas: 6, aneis: 3, confete: 18 }[truque.efeito] || 0;
        lancarEfeito(truque.efeito, quantidade);
        agendar(() => limparTruque(), truque.duracaoMs);
        return true;
      }

      if (shouldReduceMotion()) {
        LupinFace.setEmotion(id === 'nap' ? 'sleepy' : 'happy', { durationMs: truque.duracaoMs });
        internal.truqueAtivo = null;
        return true;
      }

      const quadros = truque.quadros;
      let indice = 0;
      const mostrar = () => {
        if (!internal.corpo) return;
        internal.corpo.setAttribute('src', BASE + 'corpo/' + quadros[indice % quadros.length] + '.svg');
        internal.corpo.hidden = false;
        indice += 1;
      };
      internal.root.classList.add('lupin-corpo-inteiro');
      mostrar();
      for (let t = truque.intervaloMs; t < truque.duracaoMs; t += truque.intervaloMs) {
        agendar(mostrar, t);
      }
      agendar(() => limparTruque(), truque.duracaoMs);
      return true;
    },

    isTrickPlaying() {
      return internal.truqueAtivo !== null;
    },
  };

  LupinFace.resolverCamadas = resolverCamadas;
  global.LupinFace = LupinFace;
})(typeof window !== 'undefined' ? window : globalThis);
