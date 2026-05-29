import React from "react";
import { render, type RenderOptions } from "@testing-library/react";
import { Toaster } from "sonner";
import ColumnConfigProvider from "../components/ColumnConfigProvider";

function TestProviders({ children }: { children: React.ReactNode }) {
  return (
    <ColumnConfigProvider>
      {children}
      <Toaster richColors position="top-right" theme="dark" />
    </ColumnConfigProvider>
  );
}

export function renderWithProviders(ui: React.ReactElement, options?: Omit<RenderOptions, "wrapper">) {
  return render(ui, { wrapper: TestProviders, ...options });
}
