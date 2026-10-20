import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Xianyu Agent Desk｜闲鱼智能客服控制台",
  description: "包含意图识别、多轮改写、混合粗排与模型精排的闲鱼自动回复控制台。",
  icons: { icon: "/favicon.svg", shortcut: "/favicon.svg" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
