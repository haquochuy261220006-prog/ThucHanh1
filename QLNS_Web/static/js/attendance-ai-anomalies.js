(() => {
    const form = document.getElementById('ai-anomaly-form');
    if (!form) return;

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const output = document.getElementById('ai-anomaly-explanation');
        const button = form.querySelector('button[type="submit"]');
        const token = document.querySelector('meta[name="csrf-token"]')?.content;
        button.disabled = true;
        output.textContent = 'Đang tạo giải thích…';
        try {
            const response = await fetch(form.action, {
                method: 'POST',
                headers: { 'X-CSRF-Token': token || '' },
                body: new FormData(form),
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Không thể giải thích số liệu.');
            output.textContent = result.explanation;
        } catch (error) {
            output.textContent = error.message || 'Không thể kết nối dịch vụ AI.';
        } finally {
            button.disabled = false;
        }
    });
})();
