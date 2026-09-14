(() => {
  'use strict';

  const $ = id => document.getElementById(id);
  const copy = {
    zh: {
      'nav.conversations': '对话', 'portal.label': '客户门户', 'portal.title': '我的咨询',
      'chat.new': '开始咨询', 'chat.search': '搜索咨询', 'chat.recent': '最近咨询',
      'chat.inquiry': '产品咨询', 'status.online': '在线服务', 'status.connecting': '正在连接',
      'status.consultation': '产品咨询', 'status.quote': '报价申请', 'chat.delete': '删除咨询',
      'assistant.identity': 'NanoClaw 产品顾问',
      'welcome.title': '欢迎咨询产品与采购问题',
      'welcome.subtitle': '可以先了解产品、规格、起订量、库存和交期；确认采购意向后再提交报价申请。',
      'chat.inputLabel': '咨询内容', 'chat.placeholder': '咨询产品、规格、MOQ、库存或交期…',
      'chat.send': '发送消息', 'chat.quote': '申请报价',
      'chat.quoteTemplate': '我想申请报价：\n产品：\n数量：\n目的地：\n贸易术语：\n期望交期：',
      'chat.serviceUnavailable': '服务暂时不可用，请稍后重试或联系销售团队。',
      'portal.privacy': '产品信息来自受控查询；正式报价和交期承诺由销售团队审核确认。',
      'prompt.usbcLabel': 'USB-C 数据线', 'prompt.usbcText': '你们有哪些 USB-C 数据线？请介绍规格、MOQ、参考价格和交期。',
      'prompt.tabletLabel': '工业平板', 'prompt.tabletText': '你们有哪些工业平板？请介绍主要规格、MOQ和交期。',
      'chat.newTitle': '新的产品咨询', 'chat.newHint': '可以先咨询产品和采购条件，需要正式报价时再提交报价申请。',
      'common.cancel': '取消', 'common.create': '开始咨询', 'common.close': '关闭', 'time.today': '今天', 'time.yesterday': '昨天',
      'auth.account': '客户账号', 'auth.loginButton': '客户登录', 'auth.title': '客户登录', 'auth.hint': '登录后可恢复本账号历史对话。',
      'auth.email': '邮箱', 'auth.password': '密码', 'auth.login': '登录', 'auth.logout': '退出',
      'auth.emailPlaceholder': 'name@example.com', 'auth.passwordPlaceholder': '请输入密码', 'auth.security': '登录信息将通过安全连接提交。'
    },
    en: {
      'nav.conversations': 'Conversations', 'portal.label': 'CUSTOMER PORTAL', 'portal.title': 'My conversations',
      'chat.new': 'Start a chat', 'chat.search': 'Search conversations', 'chat.recent': 'Recent conversations',
      'chat.inquiry': 'PRODUCT CONSULTATION', 'status.online': 'Online', 'status.connecting': 'Connecting',
      'status.consultation': 'Product consultation', 'status.quote': 'Quote request', 'chat.delete': 'Delete conversation',
      'assistant.identity': 'NanoClaw Product Advisor',
      'welcome.title': 'Ask us about products and purchasing',
      'welcome.subtitle': 'Explore products, specifications, MOQ, availability, and lead time first. Request a formal quotation when you are ready.',
      'chat.inputLabel': 'Message', 'chat.placeholder': 'Ask about products, specifications, MOQ, availability, or lead time…',
      'chat.send': 'Send message', 'chat.quote': 'Request quote',
      'chat.quoteTemplate': 'I would like a quotation:\nProduct:\nQuantity:\nDestination:\nIncoterm:\nRequired delivery date:',
      'chat.serviceUnavailable': 'The service is temporarily unavailable. Please try again later or contact our sales team.',
      'portal.privacy': 'Product information comes from controlled queries. Formal prices and delivery commitments are confirmed by our sales team.',
      'prompt.usbcLabel': 'USB-C data cables', 'prompt.usbcText': 'Which USB-C data cables do you offer? Please share specifications, MOQ, indicative price, and lead time.',
      'prompt.tabletLabel': 'Industrial tablets', 'prompt.tabletText': 'Which industrial tablets do you offer? Please share key specifications, MOQ, and lead time.',
      'chat.newTitle': 'New product consultation', 'chat.newHint': 'Ask about products and purchasing terms first, then request a formal quotation when ready.',
      'common.cancel': 'Cancel', 'common.create': 'Start chat', 'common.close': 'Close', 'time.today': 'Today', 'time.yesterday': 'Yesterday',
      'auth.account': 'Customer account', 'auth.loginButton': 'Sign in', 'auth.title': 'Customer login', 'auth.hint': 'Sign in to restore your account conversations.',
      'auth.email': 'Email', 'auth.password': 'Password', 'auth.login': 'Sign in', 'auth.logout': 'Sign out',
      'auth.emailPlaceholder': 'name@example.com', 'auth.passwordPlaceholder': 'Enter your password', 'auth.security': 'Your sign-in details are submitted over a secure connection.'
    },
    de: {
      'nav.conversations': 'Gespräche', 'portal.label': 'KUNDENPORTAL', 'portal.title': 'Meine Gespräche',
      'chat.new': 'Beratung starten', 'chat.search': 'Gespräche suchen', 'chat.recent': 'Letzte Gespräche',
      'chat.inquiry': 'PRODUKTBERATUNG', 'status.online': 'Online', 'status.connecting': 'Verbindung',
      'status.consultation': 'Produktberatung', 'status.quote': 'Angebotsanfrage', 'chat.delete': 'Gespräch löschen',
      'assistant.identity': 'NanoClaw Produktberater',
      'welcome.title': 'Fragen Sie uns zu Produkten und Einkauf',
      'welcome.subtitle': 'Informieren Sie sich zunächst über Produkte, Spezifikationen, Mindestmenge, Verfügbarkeit und Lieferzeit. Fordern Sie danach ein Angebot an.',
      'chat.inputLabel': 'Nachricht', 'chat.placeholder': 'Fragen zu Produkten, Spezifikationen, Mindestmenge, Bestand oder Lieferzeit…',
      'chat.send': 'Nachricht senden', 'chat.quote': 'Angebot anfordern',
      'chat.quoteTemplate': 'Ich möchte ein Angebot anfordern:\nProdukt:\nMenge:\nZielort:\nIncoterm:\nGewünschter Liefertermin:',
      'chat.serviceUnavailable': 'Der Dienst ist vorübergehend nicht verfügbar. Bitte versuchen Sie es später erneut oder kontaktieren Sie den Vertrieb.',
      'portal.privacy': 'Produktinformationen stammen aus kontrollierten Abfragen. Verbindliche Preise und Lieferzusagen bestätigt unser Vertrieb.',
      'prompt.usbcLabel': 'USB-C-Datenkabel', 'prompt.usbcText': 'Welche USB-C-Datenkabel bieten Sie an? Bitte nennen Sie Spezifikationen, Mindestmenge, Richtpreis und Lieferzeit.',
      'prompt.tabletLabel': 'Industrie-Tablets', 'prompt.tabletText': 'Welche Industrie-Tablets bieten Sie an? Bitte nennen Sie Spezifikationen, Mindestmenge und Lieferzeit.',
      'chat.newTitle': 'Neue Produktberatung', 'chat.newHint': 'Fragen Sie zunächst zu Produkten und Konditionen und fordern Sie bei Bedarf ein formelles Angebot an.',
      'common.cancel': 'Abbrechen', 'common.create': 'Beratung starten', 'common.close': 'Schließen', 'time.today': 'Heute', 'time.yesterday': 'Gestern',
      'auth.account': 'Kundenkonto', 'auth.loginButton': 'Anmelden', 'auth.title': 'Kundenanmeldung', 'auth.hint': 'Melden Sie sich an, um Ihre Anfragen wiederherzustellen.',
      'auth.email': 'E-Mail', 'auth.password': 'Passwort', 'auth.login': 'Anmelden', 'auth.logout': 'Abmelden',
      'auth.emailPlaceholder': 'name@example.com', 'auth.passwordPlaceholder': 'Passwort eingeben', 'auth.security': 'Ihre Anmeldedaten werden über eine sichere Verbindung übertragen.'
    }
  };

  const browserLanguage = (navigator.language || 'en').toLowerCase();
  let lang = localStorage.getItem('nanoclaw-customer-language')
    || (browserLanguage.startsWith('zh') ? 'zh' : browserLanguage.startsWith('de') ? 'de' : 'en');
  const t = key => copy[lang][key] || copy.en[key] || key;
  let conversations = [
    { id: crypto.randomUUID(), title: 'USB-C data cables', dayKey: 'time.today', kind: 'consultation' },
    { id: crypto.randomUUID(), title: 'Industrial tablets', dayKey: 'time.yesterday', kind: 'consultation' }
  ];
  let active = conversations[0].id;
  const messagesByConversation = Object.fromEntries(conversations.map(item => [item.id, []]));
  const welcomeMarkup = $('messages').innerHTML;
  let socket = null;
  let reconnectTimer = null;
  let authenticated = false;
  let csrfToken = '';

  const updateAccountButton = () => {
    const label = t(authenticated ? 'auth.account' : 'auth.loginButton');
    $('customerAccountLabel').textContent = label;
    $('customerAccountLabel').dataset.i18n = authenticated ? 'auth.account' : 'auth.loginButton';
    $('customerAccount').setAttribute('aria-label', label);
  };

  const cookieValue = name => document.cookie.split('; ').find(item => item.startsWith(`${name}=`))?.split('=').slice(1).join('=') || '';
  const customerApi = async (path, options = {}) => {
    const headers = { ...(options.headers || {}) };
    if (csrfToken && !['GET', 'HEAD'].includes((options.method || 'GET').toUpperCase())) {
      headers['X-CSRF-Token'] = decodeURIComponent(csrfToken);
    }
    const response = await fetch(path, { credentials: 'same-origin', ...options, headers });
    if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || `HTTP ${response.status}`);
    return response.status === 204 ? null : response.json();
  };

  const loadServerMessages = async conversationId => {
    if (!authenticated) return;
    const payload = await customerApi(`/api/customer/conversations/${encodeURIComponent(conversationId)}/messages?limit=200`);
    messagesByConversation[conversationId] = payload.items
      .filter(item => item.role === 'user' || item.role === 'assistant')
      .map(item => ({ role: item.role, content: typeof item.content === 'string' ? item.content : JSON.stringify(item.content) }));
  };

  const loadServerConversations = async () => {
    const sessionResponse = await fetch('/api/customer/auth/session', { credentials: 'same-origin' });
    if (!sessionResponse.ok) return false;
    const session = await sessionResponse.json();
    csrfToken = cookieValue('nanoclaw_customer_csrf');
    if (!session.authenticated) return false;
    const payload = await customerApi('/api/customer/conversations?limit=100');
    authenticated = true;
    updateAccountButton();
    conversations = payload.items.map(item => ({
      id: item.conversation_id, title: item.title, dayKey: 'time.today', version: item.version,
      kind: 'consultation',
    }));
    conversations.forEach(item => { messagesByConversation[item.id] ||= []; });
    active = conversations[0]?.id || '';
    if (active) await loadServerMessages(active);
    $('conversationTitle').textContent = conversations[0]?.title || t('portal.title');
    renderList();
    renderMessages();
    return true;
  };

  const workflowCopy = {
    zh: ['报价申请进度', '需求已提交', '销售确认', '准备报价', '报价可查看', '等待提交', '销售处理中', '报价已回复'],
    en: ['Quote request progress', 'Request submitted', 'Sales confirmation', 'Prepare quote', 'Quote available', 'Waiting', 'Sales reviewing', 'Quote ready'],
    de: ['Status der Angebotsanfrage', 'Anfrage gesendet', 'Vertrieb bestätigt', 'Angebot vorbereiten', 'Angebot verfügbar', 'Warten', 'Vertrieb prüft', 'Angebot bereit']
  };

  const technicalErrorPattern = /(API\s*调用失败|Error\s*code\s*:\s*\d+|Token\s+is\s+invalid|invalid\s+(?:api\s+)?key|authentication\s+failed)/i;
  const safeAssistantMessage = value => technicalErrorPattern.test(value)
    ? t('chat.serviceUnavailable') : value;
  const explicitQuotePattern = /(申请报价|请报价|正式报价|询价单|\bRFQ\b|request\s+(?:a\s+)?quote|formal\s+quotation|angebot\s+anfordern)/i;

  const appendMessage = (role, value) => {
    const row = document.createElement('article');
    row.className = `portal-message-row ${role}`;
    const avatar = document.createElement('span');
    const isAssistant = role === 'assistant';
    avatar.className = `portal-message-avatar ${isAssistant ? 'brand-avatar' : 'customer-avatar'}`;
    avatar.setAttribute('role', 'img');
    avatar.setAttribute('aria-label', isAssistant ? t('assistant.identity') : (lang === 'zh' ? '客户' : lang === 'de' ? 'Kunde' : 'Customer'));
    avatar.innerHTML = isAssistant
      ? '<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M10.5 11.5 7 7m14.5 4.5L25 7M10 12c-3.7.7-5.2 4.8-3 7.8 1.8 2.5 5.5 2.8 8 .7m7-8.5c3.7.7 5.2 4.8 3 7.8-1.8 2.5-5.5 2.8-8 .7"/><path d="M11 12.5c0-2.4 2.2-4.5 5-4.5s5 2.1 5 4.5v7c0 2.7-2.2 4.8-5 4.8s-5-2.1-5-4.8z"/><circle cx="14" cy="14" r="1"/><circle cx="18" cy="14" r="1"/></svg>'
      : '<svg viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="11.5" r="5"/><path d="M7.5 26c.8-5.5 4-8.3 8.5-8.3s7.7 2.8 8.5 8.3"/></svg>';
    const message = document.createElement('div');
    message.className = `preview-message ${role}`;
    if (role === 'assistant') {
      message.classList.add('markdown-body');
      message.innerHTML = window.NanoClawMarkdown?.render(safeAssistantMessage(value)) || '';
    } else {
      message.textContent = value;
    }
    if (isAssistant) row.append(avatar, message);
    else row.append(message, avatar);
    $('messages').append(row);
  };

  const renderMessages = () => {
    const messages = messagesByConversation[active] || [];
    $('messages').innerHTML = messages.length ? '' : welcomeMarkup;
    messages.forEach(item => appendMessage(item.role, item.content));
    $('messages').scrollTop = $('messages').scrollHeight;
  };

  const showWorkflow = stage => {
    let panel = document.querySelector('.customer-workflow-panel');
    if (!panel) {
      panel = document.createElement('aside');
      panel.className = 'customer-workflow-panel';
      document.querySelector('#conversationPage').append(panel);
    }
    const labels = workflowCopy[lang] || workflowCopy.en;
    panel.innerHTML = `<header><strong>${labels[0]}</strong><small>${labels[stage === 'done' ? 7 : stage === 'processing' ? 6 : 5]}</small></header><ol>${labels.slice(1, 5).map((label, index) => `<li class="${stage === 'done' || index === 0 || (stage === 'processing' && index < 3) ? 'complete' : index === 3 && stage === 'processing' ? 'active' : ''}"><i>${index + 1}</i><span>${label}</span></li>`).join('')}</ol>`;
  };

  const hideWorkflow = () => document.querySelector('.customer-workflow-panel')?.remove();
  const updateConversationMode = () => {
    const current = conversations.find(item => item.id === active);
    $('inquiryNumber').textContent = t(current?.kind === 'quote' ? 'status.quote' : 'status.consultation');
    if (current?.kind !== 'quote') hideWorkflow();
  };

  const setConnection = online => {
    const status = document.querySelector('.status-pill span');
    if (status) status.textContent = t(online ? 'status.online' : 'status.connecting');
    $('inquiryForm').querySelector('button[type="submit"]').disabled = !online;
  };

  const connect = () => {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    socket = new WebSocket(`${protocol}//${location.host}/ws`);
    setConnection(false);
    socket.onopen = () => setConnection(true);
    socket.onmessage = event => {
      let payload;
      try { payload = JSON.parse(event.data); } catch (_error) { return; }
      if (payload.type !== 'assistant.message' || typeof payload.content !== 'string') return;
      const conversationId = payload.conversation_id;
      if (!messagesByConversation[conversationId]) return;
      messagesByConversation[conversationId].push({ role: 'assistant', content: payload.content });
      if (conversationId === active) renderMessages();
      if (conversationId === active
          && conversations.find(item => item.id === active)?.kind === 'quote') showWorkflow('done');
    };
    socket.onclose = () => {
      setConnection(false);
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(connect, 3000);
    };
    socket.onerror = () => socket.close();
  };

  const renderList = () => {
    $('conversationList').innerHTML = conversations.map(conversation => `
      <button class="customer-conversation ${conversation.id === active ? 'active' : ''}" data-id="${conversation.id}">
        <strong>${conversation.title}</strong><small>${t(conversation.dayKey)} · ${t(conversation.kind === 'quote' ? 'status.quote' : 'status.consultation')}</small>
      </button>`).join('');
    $('chatCount').textContent = conversations.length;
    $('conversationList').querySelectorAll('button').forEach(button => {
      button.onclick = async () => {
        active = button.dataset.id;
        $('conversationTitle').textContent = conversations.find(item => item.id === active).title;
        if (authenticated) await loadServerMessages(active);
        renderList();
        renderMessages();
        updateConversationMode();
      };
    });
  };

  const setLanguage = next => {
    lang = copy[next] ? next : 'en';
    localStorage.setItem('nanoclaw-customer-language', lang);
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : lang;
    $('languageToggle').textContent = { zh: '中', en: 'EN', de: 'DE' }[lang];
    document.querySelectorAll('[data-i18n]').forEach(element => {
      element.textContent = t(element.dataset.i18n);
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(element => {
      element.placeholder = t(element.dataset.i18nPlaceholder);
    });
    document.querySelectorAll('[data-i18n-aria]').forEach(element => {
      element.setAttribute('aria-label', t(element.dataset.i18nAria));
    });
    updateAccountButton();
    renderList();
    updateConversationMode();
  };

  const dialog = $('customerDialog');
  const authDialog = $('customerAuthDialog');
  $('customerAccount').onclick = () => {
    $('customerAuthStatus').textContent = t('auth.hint');
    $('customerAuthStatus').dataset.state = 'neutral';
    $('customerLogout').hidden = !authenticated;
    $('customerAuthForm').querySelector('button[type="submit"]').hidden = authenticated;
    authDialog.showModal();
  };
  $('customerAuthForm').onsubmit = async event => {
    event.preventDefault();
    const submitter = event.submitter;
    if (submitter?.value === 'cancel' || submitter?.hasAttribute('data-auth-close')) {
      authDialog.close('cancel');
      return;
    }
    try {
      await customerApi('/api/customer/auth/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: $('customerAuthEmail').value,
          password: $('customerAuthPassword').value, locale: lang }),
      });
      csrfToken = cookieValue('nanoclaw_customer_csrf');
      authDialog.close();
      await loadServerConversations();
      socket?.close();
    } catch (_error) {
      $('customerAuthStatus').textContent = lang === 'zh' ? '登录失败，请检查凭据。' : lang === 'de' ? 'Anmeldung fehlgeschlagen.' : 'Sign-in failed.';
      $('customerAuthStatus').dataset.state = 'error';
    } finally {
      $('customerAuthPassword').value = '';
    }
  };
  $('customerLogout').onclick = async () => {
    await customerApi('/api/customer/auth/logout', { method: 'POST' });
    authenticated = false;
    authDialog.close();
    location.reload();
  };
  $('newInquiry').onclick = () => dialog.showModal();
  dialog.addEventListener('close', async () => {
    if (dialog.returnValue !== 'confirm') return;
    let created;
    if (authenticated) {
      created = await customerApi('/api/customer/conversations', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: t('chat.newTitle') }),
      });
    }
    const id = created?.conversation_id || crypto.randomUUID();
    conversations.unshift({ id, title: created?.title || t('chat.newTitle'),
      dayKey: 'time.today', version: created?.version || 1, kind: 'consultation' });
    messagesByConversation[id] = [];
    active = id;
    $('conversationTitle').textContent = t('chat.newTitle');
    renderList();
    renderMessages();
    updateConversationMode();
    $('inquiryInput').focus();
  });
  $('deleteConversation').onclick = async () => {
    const current = conversations.find(conversation => conversation.id === active);
    if (authenticated && current) {
      await customerApi(`/api/customer/conversations/${encodeURIComponent(active)}?version=${current.version}`, {
        method: 'DELETE', headers: { 'Idempotency-Key': crypto.randomUUID() },
      });
    }
    conversations = conversations.filter(conversation => conversation.id !== active);
    delete messagesByConversation[active];
    active = conversations[0]?.id || '';
    $('conversationTitle').textContent = conversations[0]?.title || t('portal.title');
    renderList();
    renderMessages();
    updateConversationMode();
  };
  $('inquiryForm').onsubmit = event => {
    event.preventDefault();
    const value = $('inquiryInput').value.trim();
    if (!value) return;
    if (!active || socket?.readyState !== WebSocket.OPEN) return;
    const current = conversations.find(item => item.id === active);
    if (current && (current.kind === 'quote' || explicitQuotePattern.test(value))) current.kind = 'quote';
    messagesByConversation[active].push({ role: 'user', content: value });
    renderMessages();
    updateConversationMode();
    if (current?.kind === 'quote') showWorkflow('processing');
    socket.send(JSON.stringify({ type: 'chat.message', protocol_version: 2,
      conversation_id: active, request_id: crypto.randomUUID(), language: lang, content: value }));
    $('inquiryInput').value = '';
  };
  $('quoteRequest').onclick = () => {
    const current = conversations.find(item => item.id === active);
    if (current) current.kind = 'quote';
    $('inquiryInput').value = t('chat.quoteTemplate');
    updateConversationMode();
    renderList();
    $('inquiryInput').focus();
  };
  document.querySelectorAll('[data-prompt-key]').forEach(button => {
    button.onclick = () => {
      $('inquiryInput').value = t(button.dataset.promptKey);
      $('inquiryInput').focus();
    };
  });
  $('languageToggle').onclick = () => $('languageMenu').classList.toggle('open');
  document.querySelectorAll('[data-language]').forEach(button => {
    button.onclick = () => {
      $('languageMenu').classList.remove('open');
      $('languageToggle').setAttribute('aria-expanded', 'false');
      setLanguage(button.dataset.language);
    };
  });
  window.addEventListener('storage', event => {
    if (event.key === 'nanoclaw-customer-language' && copy[event.newValue]) {
      setLanguage(event.newValue);
    }
  });
  window.addEventListener('nanoclaw:customer-language-change', event => {
    if (copy[event.detail?.language]) setLanguage(event.detail.language);
  });
  setLanguage(lang);
  renderMessages();
  loadServerConversations().catch(() => false).finally(connect);
})();
