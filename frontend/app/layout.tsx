import type { ReactNode } from "react";
import "./globals.css";
export const metadata = {title: "the boring-travel company | Good trips. Less fuss.", description: "Discover thoughtful stays in Lisbon, Kyoto, and Vancouver. Less planning, more being there. Meet the boring-travel company."};
export default function Layout({children}: {children: ReactNode}) {return <html lang="en"><body>{children}</body></html>}
