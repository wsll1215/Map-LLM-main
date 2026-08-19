/**
 * 地图管理 Admin 增强脚本
 */

(function() {
    'use strict';

    // 等待 DOM 加载完成
    document.addEventListener('DOMContentLoaded', function() {
        console.log('Admin Mapping JS loaded');
        
        // 初始化功能
        initDownloadButtons();
        initDeleteButtons();
        initImagePreview();
    });

    /**
     * 初始化下载按钮
     */
    function initDownloadButtons() {
        const downloadButtons = document.querySelectorAll('[onclick*="downloadSession"]');

        console.log('Found download buttons:', downloadButtons.length);

        downloadButtons.forEach(button => {
            button.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();

                const sessionId = this.getAttribute('data-session-id');
                if (!sessionId) {
                    // 从 onclick 属性中提取 session_id
                    const onclickAttr = this.getAttribute('onclick');
                    console.log('onclick attribute:', onclickAttr);
                    const match = onclickAttr.match(/downloadSession\((\d+)\)/);
                    if (match) {
                        console.log('Extracted session ID:', match[1]);
                        downloadSession(match[1]);
                    } else {
                        console.error('Failed to extract session ID from:', onclickAttr);
                    }
                } else {
                    downloadSession(sessionId);
                }
            });
        });
    }

    /**
     * 下载会话文件
     */
    function downloadSession(sessionId) {
        console.log('Downloading session:', sessionId);

        // 获取下载按钮元素
        const downloadBtn = document.getElementById(`download-btn-${sessionId}`);
        let originalContent = '';

        // 保存原始按钮内容并设置为下载中状态
        if (downloadBtn) {
            originalContent = downloadBtn.innerHTML;
            downloadBtn.innerHTML = '⏳ 下载中...';
            downloadBtn.style.color = '#999';
            downloadBtn.style.pointerEvents = 'none'; // 禁用点击
        }

        // 显示加载提示
        const loadingMsg = showMessage('正在准备下载...', 'info');

        // 发起下载请求
        fetch(`/mapping/api/admin/sessions/${sessionId}/download/`, {
            method: 'GET',
            credentials: 'same-origin'
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('下载失败');
            }
            return response.blob();
        })
        .then(blob => {
            // 创建下载链接
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `session_${sessionId}.zip`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);

            hideMessage(loadingMsg);
            showMessage('下载成功！', 'success');

            // 恢复按钮状态
            if (downloadBtn) {
                downloadBtn.innerHTML = originalContent;
                downloadBtn.style.color = '#4CAF50';
                downloadBtn.style.pointerEvents = 'auto'; // 恢复点击
            }
        })
        .catch(error => {
            console.error('Download error:', error);
            hideMessage(loadingMsg);
            showMessage('下载失败：' + error.message, 'error');

            // 恢复按钮状态
            if (downloadBtn) {
                downloadBtn.innerHTML = originalContent;
                downloadBtn.style.color = '#4CAF50';
                downloadBtn.style.pointerEvents = 'auto'; // 恢复点击
            }
        });
    }

    /**
     * 初始化删除按钮
     */
    function initDeleteButtons() {
        const deleteButtons = document.querySelectorAll('[onclick*="deleteSession"]');

        console.log('Found delete buttons:', deleteButtons.length);

        deleteButtons.forEach(button => {
            button.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();

                const sessionId = this.getAttribute('data-session-id');
                if (!sessionId) {
                    // 从 onclick 属性中提取 session_id
                    const onclickAttr = this.getAttribute('onclick');
                    console.log('onclick attribute:', onclickAttr);
                    const match = onclickAttr.match(/deleteSession\((\d+)\)/);
                    if (match) {
                        console.log('Extracted session ID:', match[1]);
                        confirmDeleteSession(match[1]);
                    } else {
                        console.error('Failed to extract session ID from:', onclickAttr);
                    }
                } else {
                    confirmDeleteSession(sessionId);
                }
            });
        });
    }

    /**
     * 确认删除会话
     */
    function confirmDeleteSession(sessionId) {
        if (!confirm('确定要删除这个会话吗？此操作不可恢复！')) {
            return;
        }
        
        console.log('Deleting session:', sessionId);
        
        // 显示加载提示
        const loadingMsg = showMessage('正在删除...', 'info');
        
        // 发起删除请求
        fetch(`/mapping/api/admin/sessions/${sessionId}/delete/`, {
            method: 'DELETE',
            credentials: 'same-origin',
            headers: {
                'X-CSRFToken': getCookie('csrftoken')
            }
        })
        .then(response => response.json())
        .then(data => {
            hideMessage(loadingMsg);
            
            if (data.success) {
                showMessage('删除成功！', 'success');
                
                // 刷新页面
                setTimeout(() => {
                    window.location.reload();
                }, 1000);
            } else {
                showMessage('删除失败：' + data.error, 'error');
            }
        })
        .catch(error => {
            console.error('Delete error:', error);
            hideMessage(loadingMsg);
            showMessage('删除失败：' + error.message, 'error');
        });
    }

    /**
     * 初始化图片预览
     */
    function initImagePreview() {
        const images = document.querySelectorAll('img[src*="generated_maps"]');
        
        images.forEach(img => {
            img.style.cursor = 'pointer';
            
            img.addEventListener('click', function() {
                showImageModal(this.src);
            });
        });
    }

    /**
     * 显示图片模态框
     */
    function showImageModal(imageSrc) {
        // 创建模态框
        const modal = document.createElement('div');
        modal.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.9);
            z-index: 10000;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
        `;
        
        const img = document.createElement('img');
        img.src = imageSrc;
        img.style.cssText = `
            max-width: 90%;
            max-height: 90%;
            border-radius: 4px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
        `;
        
        modal.appendChild(img);
        document.body.appendChild(modal);
        
        // 点击关闭
        modal.addEventListener('click', function() {
            document.body.removeChild(modal);
        });
        
        // ESC 键关闭
        const escHandler = function(e) {
            if (e.key === 'Escape') {
                if (document.body.contains(modal)) {
                    document.body.removeChild(modal);
                }
                document.removeEventListener('keydown', escHandler);
            }
        };
        document.addEventListener('keydown', escHandler);
    }



    /**
     * 格式化字节大小
     */
    function formatBytes(bytes) {
        if (bytes === 0) return '0 B';
        
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    /**
     * 显示消息提示
     */
    function showMessage(message, type = 'info') {
        const colors = {
            'info': '#2196F3',
            'success': '#4CAF50',
            'error': '#F44336',
            'warning': '#FF9800'
        };
        
        const messageDiv = document.createElement('div');
        messageDiv.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: ${colors[type]};
            color: white;
            padding: 15px 20px;
            border-radius: 4px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.2);
            z-index: 9999;
            font-size: 14px;
            max-width: 300px;
            animation: slideIn 0.3s ease;
        `;
        messageDiv.textContent = message;
        
        document.body.appendChild(messageDiv);
        
        return messageDiv;
    }

    /**
     * 隐藏消息提示
     */
    function hideMessage(messageDiv) {
        if (messageDiv && document.body.contains(messageDiv)) {
            messageDiv.style.animation = 'slideOut 0.3s ease';
            setTimeout(() => {
                if (document.body.contains(messageDiv)) {
                    document.body.removeChild(messageDiv);
                }
            }, 300);
        }
    }

    /**
     * 获取 Cookie
     */
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    // 添加 CSS 动画
    const style = document.createElement('style');
    style.textContent = `
        @keyframes slideIn {
            from {
                transform: translateX(400px);
                opacity: 0;
            }
            to {
                transform: translateX(0);
                opacity: 1;
            }
        }
        
        @keyframes slideOut {
            from {
                transform: translateX(0);
                opacity: 1;
            }
            to {
                transform: translateX(400px);
                opacity: 0;
            }
        }
    `;
    document.head.appendChild(style);

})();

