import React from "react";
import { shell } from "./ui";

interface PageStackProps {
  children: React.ReactNode;
  className?: string;
}

export default function PageStack({ children, className }: PageStackProps) {
  return <div className={[shell.sectionGap, className].filter(Boolean).join(" ")}>{children}</div>;
}
