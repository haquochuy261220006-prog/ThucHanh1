(() => {
    const token = document.querySelector('meta[name="csrf-token"]')?.content;

    document.querySelectorAll('.avatar-image').forEach((image) => {
        const showLoadedImage = () => image.classList.toggle('is-loaded', image.naturalWidth > 0);
        image.addEventListener('load', showLoadedImage, { once: true });
        image.addEventListener('error', showLoadedImage, { once: true });
        if (image.complete) showLoadedImage();
    });

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
        window.fetch = function(url, options = {}) {
            const method = (options.method || 'GET').toUpperCase();
            if (method === 'GET' || method === 'HEAD') return nativeFetch.call(this, url, options);

            const headers = new Headers(options.headers || {});
            if (!headers.has('X-CSRF-Token')) headers.set('X-CSRF-Token', token);
            return nativeFetch.call(this, url, {
                ...options,
                headers
            });
        };
    }

    document.getElementById('admin-attendance-form')?.addEventListener('submit', (event) => {
        const form = event.currentTarget;
        const employee = form.elements.MaNV;
        const option = employee.options[employee.selectedIndex];
        const action = event.submitter?.value === 'out' ? 'Chấm ra' : 'Chấm vào';
        if (!employee.value || !window.confirm(`${action} cho nhân viên:\n${option.text}\n\nXác nhận thực hiện?`)) {
            event.preventDefault();
        }
    });

    document.querySelectorAll('.attendance-confirm').forEach((form) => {
        form.addEventListener('submit', (event) => {
            const panel = document.getElementById('face-attendance');
            const name = panel?.dataset.employeeName || 'Tài khoản hiện tại';
            const code = panel?.dataset.employeeCode || 'Không có mã nhân viên';
            const action = form.dataset.actionLabel || 'Chấm công';
            if (!window.confirm(`${action} cho:\n${name}\nMã nhân viên: ${code}\n\nXác nhận thực hiện?`)) {
                event.preventDefault();
            }
        });
    });

    document.querySelectorAll('[data-select-attendance]').forEach((button) => {
        button.addEventListener('click', () => {
            const selector = document.getElementById('face-action');
            if (selector) {
                selector.value = button.dataset.selectAttendance;
                const scan = document.getElementById('face-scan');
                if (scan && !scan.disabled) {
                    scan.click();
                } else {
                    const fallback = document.getElementById(`attendance-manual-${button.dataset.selectAttendance}`);
                    fallback?.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    fallback?.querySelector('input[name="LyDo"]')?.focus({ preventScroll: true });
                }
            }
        });
    });

    const liveClock = document.getElementById('attendance-live-clock');
    if (liveClock) {
        const updateClock = () => {
            liveClock.textContent = new Intl.DateTimeFormat('vi-VN', {
                timeZone: 'Asia/Ho_Chi_Minh', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
            }).format(new Date());
        };
        updateClock();
        window.setInterval(updateClock, 1000);
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
