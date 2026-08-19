/**
 * Django Admin 地图删除功能
 * 为生成的地图卡片添加删除按钮和删除逻辑
 */

(function() {
    'use strict';

    // 获取 CSRF token
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

    const csrftoken = getCookie('csrftoken');

    // 删除地图函数
    function deleteMap(mapId, button) {
        // 确认删除
        if (!confirm('确定要删除这个地图吗？此操作将同时删除文件系统中的文件，无法撤销。')) {
            return;
        }

        // 禁用按钮，显示加载状态
        button.disabled = true;
        const originalText = button.textContent;
        button.textContent = '⏳ 删除中...';
        button.style.background = '#6c757d';

        // 发送删除请求
        fetch(`/mapping/api/admin/maps/${mapId}/delete/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrftoken
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // 删除成功，移除卡片
                const card = button.closest('[style*="display:flex"]');
                if (card) {
                    card.style.opacity = '0.5';
                    card.style.textDecoration = 'line-through';
                    
                    // 显示成功消息
                    const message = document.createElement('div');
                    message.style.cssText = 'padding:10px; background:#d4edda; color:#155724; border:1px solid #c3e6cb; border-radius:4px; margin-top:10px;';
                    message.textContent = '✅ ' + data.message;
                    card.parentNode.insertBefore(message, card.nextSibling);
                    
                    // 2秒后移除卡片
                    setTimeout(() => {
                        card.remove();
                        message.remove();
                    }, 2000);
                }
            } else {
                // 删除失败
                alert('❌ 删除失败: ' + (data.error || '未知错误'));
                button.disabled = false;
                button.textContent = originalText;
                button.style.background = '#dc3545';
            }
        })
        .catch(error => {
            console.error('删除请求出错:', error);
            alert('❌ 请求出错: ' + error.message);
            button.disabled = false;
            button.textContent = originalText;
            button.style.background = '#dc3545';
        });
    }

    // 页面加载完成后绑定事件
    document.addEventListener('DOMContentLoaded', function() {
        // 为所有删除按钮绑定点击事件
        const deleteButtons = document.querySelectorAll('.delete-map-btn');
        deleteButtons.forEach(button => {
            button.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                
                const mapId = this.getAttribute('data-map-id');
                deleteMap(mapId, this);
            });

            // 添加悬停效果
            button.addEventListener('mouseover', function() {
                this.style.background = '#c82333';
            });

            button.addEventListener('mouseout', function() {
                this.style.background = '#dc3545';
            });
        });
    });

    // 处理动态添加的内容（如果有 inline 动态添加）
    // 使用 MutationObserver 监听 DOM 变化
    const observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            if (mutation.addedNodes.length) {
                mutation.addedNodes.forEach(function(node) {
                    if (node.nodeType === 1) { // Element node
                        const deleteButtons = node.querySelectorAll('.delete-map-btn');
                        deleteButtons.forEach(button => {
                            if (!button.hasListener) {
                                button.addEventListener('click', function(e) {
                                    e.preventDefault();
                                    e.stopPropagation();
                                    
                                    const mapId = this.getAttribute('data-map-id');
                                    deleteMap(mapId, this);
                                });

                                button.addEventListener('mouseover', function() {
                                    this.style.background = '#c82333';
                                });

                                button.addEventListener('mouseout', function() {
                                    this.style.background = '#dc3545';
                                });

                                button.hasListener = true;
                            }
                        });
                    }
                });
            }
        });
    });

    // 开始监听 DOM 变化
    observer.observe(document.body, {
        childList: true,
        subtree: true
    });
})();

