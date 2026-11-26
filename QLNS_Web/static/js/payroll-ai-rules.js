(() => {
    const form = document.getElementById('ai-payroll-rule-form');
    if (!form) return;

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const status = document.getElementById('ai-payroll-rule-status');
        const button = form.querySelector('button[type="submit"]');
        const policyInput = document.querySelector('textarea[name="QuyTacJson"]');
        const token = document.querySelector('meta[name="csrf-token"]')?.content;
        if (!policyInput || !token) {
            status.textContent = 'Không tìm thấy mẫu JSON hoặc token bảo mật. Tải lại trang.';
            return;
        }

        button.disabled = true;
        status.textContent = 'Đang yêu cầu AI diễn giải…';
        const body = new URLSearchParams(new FormData(form));
        body.set('BasePolicy', policyInput.value);
        try {
            const response = await fetch(form.action, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
                    'X-CSRF-Token': token,
                },
                body,
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Không thể diễn giải quy tắc.');
            policyInput.value = JSON.stringify(result.policy, null, 2);
            const policyDetails = policyInput.closest('details');
            if (policyDetails) policyDetails.open = true;
            status.textContent = result.message;
        } catch (error) {
            status.textContent = error.message || 'Không thể kết nối dịch vụ AI.';
        } finally {
            button.disabled = false;
        }
    });
})();
