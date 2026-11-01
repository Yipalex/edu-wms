import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { ConfigProvider, App as AntApp } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import App from './App';
import ErrorBoundary from './components/ErrorBoundary';
import './index.css';

dayjs.locale('zh-cn');

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  },
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          // 墨·纸·印 色板
          colorPrimary: '#B03A2A', // 印
          colorInfo: '#31565E', // 黛
          colorSuccess: '#3E7C4F', // 苔
          colorWarning: '#A9762B', // 赭
          colorError: '#B03A2A', // 印兼作危险色
          colorText: '#26231F', // 墨
          colorTextSecondary: '#55504A',
          colorTextTertiary: '#8A847B',
          colorBgLayout: '#F6F3EC', // 纸
          colorBorder: '#E4DFD3',
          colorBorderSecondary: '#EDE9E0',
          borderRadius: 8,
          fontFamily:
            'MiSans, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif',
          fontSize: 13,
        },
        components: {
          Card: { borderRadiusLG: 12 },
          Tag: { borderRadiusSM: 999 },
        },
      }}
    >
      <AntApp>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <ErrorBoundary>
              <App />
            </ErrorBoundary>
          </BrowserRouter>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>,
);
