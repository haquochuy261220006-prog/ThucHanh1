(() => {
    const token = document.querySelector('meta[name="csrf-token"]')?.content;

    if (token) {
        document.addEventListener('submit', (event) => {
            const form = event.target;
            if (!(form instanceof HTMLFormElement) || form.method.toLowerCase() !== 'post') return;
            if (form.querySelector('input[name="csrf_token"]')) return;

            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'csrf_token';
            input.value = token;
            form.appendChild(input);
        }, true);

        const nativeFetch = window.fetch;
        window.fetch = function (url, options = {}) {
            const method = (options.method || 'GET').toUpperCase();
            if (method === 'GET' || method === 'HEAD') return nativeFetch.call(this, url, options);

            const headers = new Headers(options.headers || {});
            if (!headers.has('X-CSRF-Token')) headers.set('X-CSRF-Token', token);
            return nativeFetch.call(this, url, { ...options, headers });
        };
    }

    const menu = document.querySelector('.menu-toggle');
    if (!menu) return;

    const closeMenu = () => {
        document.body.classList.remove('nav-open');
        menu.setAttribute('aria-expanded', 'false');
        menu.setAttribute('aria-label', 'Mở điều hướng');
    };

    menu.addEventListener('click', () => {
        const isOpen = document.body.classList.toggle('nav-open');
        menu.setAttribute('aria-expanded', String(isOpen));
        menu.setAttribute('aria-label', isOpen ? 'Đóng điều hướng' : 'Mở điều hướng');
    });

    document.body.addEventListener('click', (event) => {
        if (event.target === document.body && document.body.classList.contains('nav-open')) closeMenu();
    });
    document.querySelectorAll('.sidebar .nav').forEach((link) => link.addEventListener('click', closeMenu));
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') closeMenu();
    });
    window.addEventListener('resize', () => {
        if (window.innerWidth > 760) closeMenu();
    });
})();
