import React from 'react';

interface Props {
  children: React.ReactNode;
}

interface State {
  error: Error | null;
  info: string;
}

/**
 * 全局错误边界：任何页面组件抛错时兜底展示，避免整站白屏。
 * 不依赖 antd（若错误来自 antd 自身也能正常降级），用内联样式。
 */
export default class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null, info: '' };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // 保留到控制台，便于排查
    // eslint-disable-next-line no-console
    console.error('[ErrorBoundary]', error, info.componentStack);
    this.setState({ info: info.componentStack || '' });
  }

  private reset = () => {
    this.setState({ error: null, info: '' });
    // 回首页并刷新，清掉可能已损坏的组件树
    window.location.assign('/');
  };

  render() {
    const { error, info } = this.state;
    if (!error) return this.props.children;

    return (
      <div
        style={{
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 24,
          background: '#F6F3EC',
          fontFamily:
            "-apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif",
        }}
      >
        <div
          style={{
            maxWidth: 640,
            width: '100%',
            background: '#fff',
            borderRadius: 12,
            boxShadow: '0 8px 30px rgba(0,0,0,.12)',
            padding: 28,
          }}
        >
          <h2 style={{ margin: '0 0 8px', fontSize: 20, color: '#26231F' }}>
            页面出了点问题
          </h2>
          <p style={{ margin: '0 0 16px', color: '#55504A', fontSize: 14 }}>
            这一页加载失败，其他功能不受影响。可以先刷新重试；如果反复出现，请把下面的错误信息发给管理员。
          </p>
          <pre
            style={{
              margin: '0 0 18px',
              padding: 12,
              background: '#F6F3EC',
              borderRadius: 8,
              fontSize: 12,
              color: '#B03A2A',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              maxHeight: 220,
              overflow: 'auto',
            }}
          >
            {error.message}
            {info ? `\n${info.split('\n').slice(0, 4).join('\n')}` : ''}
          </pre>
          <div style={{ display: 'flex', gap: 12 }}>
            <button
              onClick={this.reset}
              style={{
                flex: 1,
                height: 40,
                border: 'none',
                borderRadius: 8,
                background: '#B03A2A',
                color: '#fff',
                fontSize: 15,
                cursor: 'pointer',
              }}
            >
              返回首页并刷新
            </button>
            <button
              onClick={() => window.location.reload()}
              style={{
                flex: 1,
                height: 40,
                border: '1px solid #E4DFD3',
                borderRadius: 8,
                background: '#fff',
                color: '#26231F',
                fontSize: 15,
                cursor: 'pointer',
              }}
            >
              重新加载本页
            </button>
          </div>
        </div>
      </div>
    );
  }
}
