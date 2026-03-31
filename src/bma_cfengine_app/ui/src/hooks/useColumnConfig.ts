import { useCallback, useContext, createContext } from "react";

export interface ColumnConfig {
  columnOrder: string[];
  columnSizing: Record<string, number>;
}

export interface ColumnConfigStorage {
  get(tableId: string): ColumnConfig | null;
  set(tableId: string, config: ColumnConfig): void;
}

export class SessionStorageAdapter implements ColumnConfigStorage {
  private prefix = "bma_col_cfg_";

  get(tableId: string): ColumnConfig | null {
    try {
      const raw = sessionStorage.getItem(this.prefix + tableId);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  }

  set(tableId: string, config: ColumnConfig): void {
    try {
      sessionStorage.setItem(this.prefix + tableId, JSON.stringify(config));
    } catch {
      /* quota exceeded */
    }
  }
}

export const ColumnConfigContext = createContext<ColumnConfigStorage>(
  new SessionStorageAdapter()
);

export function useColumnConfig(tableId: string) {
  const storage = useContext(ColumnConfigContext);

  const getConfig = useCallback(
    () => storage.get(tableId),
    [storage, tableId]
  );

  const setConfig = useCallback(
    (config: ColumnConfig) => storage.set(tableId, config),
    [storage, tableId]
  );

  return { getConfig, setConfig };
}
