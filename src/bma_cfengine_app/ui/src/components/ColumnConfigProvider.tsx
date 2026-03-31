import React, { useMemo } from "react";
import {
  ColumnConfigContext,
  SessionStorageAdapter,
  type ColumnConfigStorage,
} from "../hooks/useColumnConfig";

interface Props {
  adapter?: ColumnConfigStorage;
  children: React.ReactNode;
}

export default function ColumnConfigProvider({ adapter, children }: Props) {
  const storage = useMemo(() => adapter ?? new SessionStorageAdapter(), [adapter]);
  return (
    <ColumnConfigContext.Provider value={storage}>
      {children}
    </ColumnConfigContext.Provider>
  );
}
