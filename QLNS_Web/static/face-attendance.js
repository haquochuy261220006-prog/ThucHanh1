(() => {
    const panel = document.getElementById('face-attendance');
    if (!panel) return;
    const status = document.getElementById('face-status');
    const consent = document.getElementById('face-consent');
    const video = document.getElementById('face-live-video');
    const csrf = panel.dataset.csrf;
    let human;

    async function getHuman() {
        if (human) return human;
        if (!window.Human) throw new Error('Không tải được thư viện xác minh khuôn mặt. Dùng chấm công dự phòng.');
        const model = new window.Human.Human({
            modelBasePath: 'https://cdn.jsdelivr.net/npm/@vladmandic/human@3.3.6/models',
            face: {
                enabled: true,
                detector: { rotation: true, maxDetected: 2 },
                mesh: { enabled: true },
                description: { enabled: true },
                iris: { enabled: true },
                antispoof: { enabled: true },
                liveness: { enabled: true },
            },
            gesture: { enabled: true },
            body: { enabled: false },
            hand: { enabled: false },
            object: { enabled: false },
        });
        await model.load();
        human = model;
        return model;
    }

    async function embeddingFrom(source) {
        const model = await getHuman();
        const result = await model.detect(source);
        if (!result.face || result.face.length !== 1 || !result.face[0].embedding) {
            throw new Error('Cần có chính xác một khuôn mặt rõ nét.');
        }
        return Array.from(result.face[0].embedding);
    }

    async function post(url, body) {
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Face-CSRF': csrf },
            body: JSON.stringify(body),
        });
        const result = await response.json().catch(() => {
            throw new Error('Phiên đăng nhập có thể đã hết hạn. Hãy tải lại trang.');
        });
        if (!response.ok) throw new Error(result.error || 'Không thể hoàn tất thao tác.');
        return result;
    }

    async function run(button, action) {
        button.disabled = true;
        try {
            status.textContent = 'Đang xử lý trên thiết bị…';
            status.textContent = (await action()).message;
        } catch (error) {
            status.textContent = error.message || 'Không thể xác minh khuôn mặt.';
        } finally {
            button.disabled = false;
        }
    }

    async function liveScan() {
        if (!navigator.mediaDevices?.getUserMedia) {
            throw new Error('Trình duyệt không hỗ trợ camera an toàn. Dùng chấm công dự phòng.');
        }
        if (!consent.checked) throw new Error('Hãy đồng ý với mục đích xử lý dữ liệu trước khi chấm công bằng khuôn mặt.');
        const action = document.getElementById('face-action').value;
        const challenge = await post('/api/chamcong/face/challenge', {});
        const stream = await navigator.mediaDevices.getUserMedia({
            audio: false,
            video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } },
        });
        video.srcObject = stream;
        video.hidden = false;
        try {
            await video.play();
            const model = await getHuman();
            const deadline = Date.now() + 45000;
            const scores = [];
            const completed = [];
            let sideFrames = 0;
            let blinked = false;
            let centered = false;
            let embedding = null;

            while (Date.now() < deadline) {
                const result = await model.detect(video);
                const faces = result.face || [];
                if (faces.length === 1) {
                    const face = faces[0];
                    const real = Number(face.real);
                    const live = Number(face.live);
                    if (Number.isFinite(real) && Number.isFinite(live)) scores.push({ real, live });
                    const yaw = face.rotation?.angle?.yaw;
                    if (Number.isFinite(yaw)) {
                        const expected = challenge.sequence[completed.length];
                        const turned = expected === 'left' ? yaw < -0.25 : expected === 'right' ? yaw > 0.25 : false;
                        if (expected && turned) {
                            sideFrames += 1;
                            if (sideFrames >= 3) {
                                completed.push(expected);
                                sideFrames = 0;
                            }
                        } else if (expected) {
                            sideFrames = 0;
                        }
                        centered = completed.length === challenge.sequence.length && Math.abs(yaw) < 0.18;
                    }
                    const gestures = (result.gesture || []).map(item => item.gesture || '');
                    if (gestures.some(item => item.startsWith('blink '))) blinked = true;
                    if (completed.length === challenge.sequence.length && centered && blinked && face.embedding) {
                        embedding = Array.from(face.embedding);
                    }
                } else {
                    sideFrames = 0;
                }

                const text = completed.length < challenge.sequence.length
                    ? `Quay đầu sang ${challenge.sequence[completed.length] === 'left' ? 'trái' : 'phải'}`
                    : !centered ? 'Nhìn thẳng vào camera' : !blinked ? 'Chớp mắt' : 'Đang kiểm tra người thật';
                status.textContent = `${text} · ${scores.length} mẫu liveness`;
                if (embedding && scores.length >= 8) break;
                await new Promise(resolve => setTimeout(resolve, 120));
            }

            if (!embedding || scores.length < 8) {
                throw new Error('Chưa hoàn thành thử thách liveness trong thời gian cho phép. Dùng chấm công dự phòng.');
            }
            const realScore = scores.reduce((sum, item) => sum + item.real, 0) / scores.length;
            const liveScore = scores.reduce((sum, item) => sum + item.live, 0) / scores.length;
            if (completed.length !== challenge.sequence.length || !centered || !blinked) {
                throw new Error('Thử thách chuyển động chưa hoàn tất.');
            }
            return post('/api/chamcong/face/scan', {
                action,
                embedding,
                nonce: challenge.nonce,
                sequence: completed,
                blinked,
                real_score: realScore,
                live_score: liveScore,
            });
        } finally {
            stream.getTracks().forEach(track => track.stop());
            video.srcObject = null;
            video.hidden = true;
        }
    }

    document.getElementById('face-enroll')?.addEventListener('click', event => {
        if (!consent.checked) {
            status.textContent = 'Hãy xác nhận đồng ý trước khi đăng ký khuôn mặt.';
            return;
        }
        run(event.currentTarget, async () => {
            const image = document.getElementById('face-profile-photo');
            if (!image?.complete || !image.naturalWidth) {
                throw new Error('Không tải được ảnh hồ sơ. Hãy tải lại trang hoặc liên hệ quản trị viên.');
            }
            const embedding = await embeddingFrom(image);
            return post('/api/chamcong/face/enroll', {
                consent: true,
                consent_purpose: true,
                consent_version: panel.dataset.consentVersion,
                embedding,
            });
        });
    });

    document.getElementById('face-scan')?.addEventListener('click', event => run(event.currentTarget, liveScan));

    document.getElementById('face-delete')?.addEventListener('click', event => {
        if (!window.confirm('Xóa mẫu khuôn mặt đã đăng ký? Bạn cần đăng ký lại để chấm công bằng khuôn mặt.')) return;
        run(event.currentTarget, () => post('/api/chamcong/face/delete', {}));
    });
})();