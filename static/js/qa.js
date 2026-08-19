// 初始化逻辑
function initQA() {
    // 自动滚动到底部
    const scrollContainer = document.querySelector('.chat-container');
    if (scrollContainer) {
        scrollContainer.scrollTop = scrollContainer.scrollHeight;
    }

    // 焦点管理
    const questionInput = document.getElementById('questionInput');
    if (questionInput) {
        questionInput.focus();

        // 回车键提交
        questionInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                document.querySelector('#qa-form').dispatchEvent(new Event('submit'));
            }
        });
    }
}

// 表单提交处理
async function handleSubmit(e) {
    e.preventDefault();
    const form = e.target;
    const submitBtn = form.querySelector('button[type="submit"]');

    try {
        // 加载状态
        submitBtn.disabled = true;
        submitBtn.innerHTML = `<span class="spinner-border spinner-border-sm"></span> 查询中...`;

        // 构造请求
        const formData = new FormData(form);
        const response = await fetch(`/wenda?${new URLSearchParams(formData)}`, {
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'text/html'
            }
        });

        if (!response.ok) throw new Error(`HTTP错误: ${response.status}`);

        // 安全处理响应
        const html = await response.text();
        const cleanHTML = DOMPurify.sanitize(html);
        const virtualDOM = new DOMParser().parseFromString(cleanHTML, 'text/html');

        // DOM更新
        const updateContainer = document.getElementById('right-content-wrapper');
        const sourceContent = virtualDOM.getElementById('right-content-wrapper');

        if (updateContainer && sourceContent) {
            updateContainer.innerHTML = sourceContent.innerHTML;
            initQA(); // 重新初始化
        } else {
            throw new Error('页面结构异常');
        }
    } catch (error) {
        console.error('提交失败:', error);
        alert(`请求失败: ${error.message}`);
    } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = `<i class="fas fa-search me-2"></i> 获取专业解答`;
    }
}

// 事件绑定
document.addEventListener('DOMContentLoaded', () => {
    initQA();

    // 全局表单提交监听
    document.body.addEventListener('submit', (e) => {
        if (e.target.matches('#qa-form')) {
            handleSubmit(e);
        }
    });
});