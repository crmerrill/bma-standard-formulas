import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  type ColumnDef,
  type ColumnOrderState,
  type ColumnSizingState,
  type Header,
} from "@tanstack/react-table";
import { useColumnConfig } from "../hooks/useColumnConfig";
import { MONO } from "../lib/format";
const CHAR_WIDTH = 7.5;
const CELL_PADDING = 28;
const RESIZE_HANDLE = 6;
const AUTO_SIZE_SAMPLE = 50;
const AUTO_SIZE_MAX = 300;
const AUTO_SIZE_MIN = 60;

export interface DataTableColumn<T> {
  id: string;
  header: string | React.ReactNode;
  accessorFn?: (row: T) => unknown;
  accessorKey?: string;
  cell?: (value: unknown, row: T) => React.ReactNode;
  align?: "left" | "right" | "center";
  mono?: boolean;
  className?: string;
  headerClassName?: string;
  minSize?: number;
  size?: number;
  maxSize?: number;
  pinLeft?: boolean;
  enableResizing?: boolean;
}

interface Props<T> {
  tableId: string;
  columns: DataTableColumn<T>[];
  data: T[];
  maxHeight?: string | number;
  emptyMessage?: string;
  rowClassName?: (row: T, index: number) => string;
  onHeaderClick?: (columnId: string) => void;
  onRowClick?: (row: T) => void;
  headerExtra?: (columnId: string) => React.ReactNode;
  getRowId?: (row: T, index: number) => string;
  pinFirstColumn?: boolean;
}

function textLen(v: unknown): number {
  if (v == null) return 1;
  if (typeof v === "string") return v.length;
  if (typeof v === "number") return String(v).length;
  return String(v).length;
}

function headerTextLen(h: string | React.ReactNode): number {
  if (typeof h === "string") return h.length;
  return 8;
}

function estimateColumnWidth<T>(
  col: DataTableColumn<T>,
  data: T[],
): number {
  if (col.size != null) return col.size;

  const headerLen = headerTextLen(col.header);
  let maxLen = headerLen;

  const sample = data.slice(0, AUTO_SIZE_SAMPLE);
  const accessor = col.accessorFn ?? (col.accessorKey
    ? (row: T) => (row as Record<string, unknown>)[col.accessorKey!]
    : null);

  if (accessor) {
    for (const row of sample) {
      const val = accessor(row);
      const len = textLen(val);
      if (len > maxLen) maxLen = len;
    }
  }

  const px = Math.ceil(maxLen * CHAR_WIDTH) + CELL_PADDING + RESIZE_HANDLE;
  return Math.max(AUTO_SIZE_MIN, Math.min(px, AUTO_SIZE_MAX));
}

function DragHandle({
  header,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
  dragOverId,
  onClick,
}: {
  header: Header<any, unknown>;
  onDragStart: (id: string) => void;
  onDragOver: (e: React.DragEvent, id: string) => void;
  onDrop: (id: string) => void;
  onDragEnd: () => void;
  dragOverId: string | null;
  onClick?: () => void;
}) {
  return (
    <div
      draggable
      onDragStart={() => onDragStart(header.column.id)}
      onDragOver={(e) => onDragOver(e, header.column.id)}
      onDrop={() => onDrop(header.column.id)}
      onDragEnd={onDragEnd}
      onClick={onClick}
      className={`flex-1 min-w-0 cursor-grab active:cursor-grabbing select-none ${
        onClick ? "cursor-pointer hover:text-foreground transition-colors" : ""
      } ${dragOverId === header.column.id ? "opacity-50" : ""}`}
    >
      {flexRender(header.column.columnDef.header, header.getContext())}
    </div>
  );
}

export default function DataTable<T>({
  tableId,
  columns: colDefs,
  data,
  maxHeight = "500px",
  emptyMessage = "No data.",
  rowClassName,
  onHeaderClick,
  onRowClick,
  headerExtra,
  getRowId,
  pinFirstColumn = true,
}: Props<T>) {
  const { getConfig, setConfig } = useColumnConfig(tableId);
  const saved = useMemo(() => getConfig(), [tableId]);

  const [columnOrder, setColumnOrder] = useState<ColumnOrderState>(
    () => saved?.columnOrder ?? colDefs.map((c) => c.id)
  );
  const [columnSizing, setColumnSizing] = useState<ColumnSizingState>(
    () => saved?.columnSizing ?? {}
  );

  useEffect(() => {
    setColumnOrder((prev) => {
      const defIds = new Set(colDefs.map((c) => c.id));
      const filtered = prev.filter((id) => defIds.has(id));
      const missing = colDefs.map((c) => c.id).filter((id) => !filtered.includes(id));
      const merged = [...filtered, ...missing];
      if (merged.length === prev.length && merged.every((id, i) => id === prev[i])) return prev;
      return merged;
    });
  }, [colDefs]);

  const persistRef = useRef<ReturnType<typeof setTimeout>>();
  const persist = useCallback(
    (order: ColumnOrderState, sizing: ColumnSizingState) => {
      clearTimeout(persistRef.current);
      persistRef.current = setTimeout(() => {
        setConfig({ columnOrder: order, columnSizing: sizing });
      }, 500);
    },
    [setConfig]
  );

  useEffect(() => {
    persist(columnOrder, columnSizing);
  }, [columnOrder, columnSizing, persist]);

  const tanstackColumns = useMemo<ColumnDef<T, unknown>[]>(
    () =>
      colDefs.map((col, ci) => {
        const autoSize = estimateColumnWidth(col, data);
        const isFirstCol = ci === 0;
        const pin = col.pinLeft ?? (pinFirstColumn && isFirstCol);
        return {
          id: col.id,
          header: () => col.header,
          accessorFn: col.accessorFn ?? (col.accessorKey ? (row: T) => (row as Record<string, unknown>)[col.accessorKey!] : undefined),
          cell: col.cell
            ? (info: any) => col.cell!(info.getValue(), info.row.original)
            : (info: any) => {
                const v = info.getValue();
                return v == null ? "—" : String(v);
              },
          size: col.size ?? autoSize,
          minSize: col.minSize ?? AUTO_SIZE_MIN,
          maxSize: col.maxSize ?? 800,
          enableResizing: col.enableResizing !== false,
          meta: { align: col.align, mono: col.mono, className: col.className, headerClassName: col.headerClassName, pinLeft: pin },
        };
      }),
    [colDefs, data]
  );

  const table = useReactTable({
    data,
    columns: tanstackColumns,
    state: { columnOrder, columnSizing },
    onColumnOrderChange: setColumnOrder,
    onColumnSizingChange: setColumnSizing,
    columnResizeMode: "onChange",
    getCoreRowModel: getCoreRowModel(),
    getRowId: getRowId ? (row, i) => getRowId(row, i) : undefined,
  });

  const [dragSourceId, setDragSourceId] = useState<string | null>(null);
  const [dragOverId, setDragOverId] = useState<string | null>(null);

  const handleDragStart = (id: string) => setDragSourceId(id);
  const handleDragOver = (e: React.DragEvent, id: string) => {
    e.preventDefault();
    setDragOverId(id);
  };
  const handleDrop = (targetId: string) => {
    if (dragSourceId && dragSourceId !== targetId) {
      setColumnOrder((old) => {
        const newOrder = [...old];
        const fromIdx = newOrder.indexOf(dragSourceId);
        const toIdx = newOrder.indexOf(targetId);
        if (fromIdx === -1 || toIdx === -1) return old;
        newOrder.splice(fromIdx, 1);
        newOrder.splice(toIdx, 0, dragSourceId);
        return newOrder;
      });
    }
    setDragSourceId(null);
    setDragOverId(null);
  };
  const handleDragEnd = () => {
    setDragSourceId(null);
    setDragOverId(null);
  };

  const headerGroups = table.getHeaderGroups();
  const rows = table.getRowModel().rows;
  const flatHeaders = table.getFlatHeaders();
  const totalWidth = table.getTotalSize();

  return (
    <div
      className="overflow-auto"
      style={{ maxHeight: typeof maxHeight === "number" ? `${maxHeight}px` : maxHeight }}
    >
      <table
        className="border-separate border-spacing-0 text-xs"
        style={{ width: totalWidth, minWidth: "100%" }}
      >
        <colgroup>
          {flatHeaders.map((h) => (
            <col key={h.id} style={{ width: h.getSize() }} />
          ))}
        </colgroup>
        <thead className="sticky top-0 z-20">
          {headerGroups.map((hg) => (
            <tr key={hg.id} className="text-muted-foreground">
              {hg.headers.map((header) => {
                const meta = header.column.columnDef.meta as any;
                const align = meta?.align ?? "left";
                const pinLeft = meta?.pinLeft;
                const headerCls = meta?.headerClassName ?? "";
                return (
                  <th
                    key={header.id}
                    className={`relative px-3 py-1.5 whitespace-nowrap select-none bg-grid-header border-b border-border ${
                      align === "right" ? "text-right" : align === "center" ? "text-center" : "text-left"
                    } ${pinLeft ? "sticky left-0 z-30 overflow-visible" : ""} ${headerCls}`}
                  >
                    <div className="flex items-center gap-1">
                      <DragHandle
                        header={header}
                        onDragStart={handleDragStart}
                        onDragOver={handleDragOver}
                        onDrop={handleDrop}
                        onDragEnd={handleDragEnd}
                        dragOverId={dragOverId}
                        onClick={onHeaderClick ? () => onHeaderClick(header.column.id) : undefined}
                      />
                      {headerExtra?.(header.column.id)}
                    </div>
                    {header.column.getCanResize() && (
                      <div
                        onMouseDown={header.getResizeHandler()}
                        onTouchStart={header.getResizeHandler()}
                        className={`absolute right-0 top-0 h-full w-[5px] cursor-col-resize select-none touch-none ${
                          pinLeft ? "z-40" : ""
                        } ${header.column.getIsResizing() ? "bg-primary/60" : "bg-border/40 hover:bg-primary/50"}`}
                      />
                    )}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {rows.map((row, ri) => {
            const extraCls = rowClassName ? rowClassName(row.original, ri) : "";
            const defaultCls = `border-b border-border/50 hover:bg-grid-row-hover transition-colors ${
              ri % 2 === 1 ? "bg-grid-row-alt" : "bg-background"
            }`;
            return (
              <tr key={row.id} className={`${extraCls || defaultCls}${onRowClick ? " cursor-pointer" : ""}`} onClick={onRowClick ? () => onRowClick(row.original as T) : undefined}>
                {row.getVisibleCells().map((cell) => {
                  const meta = cell.column.columnDef.meta as any;
                  const align = meta?.align ?? "left";
                  const mono = meta?.mono !== false;
                  const pinLeft = meta?.pinLeft;
                  const cellCls = meta?.className ?? "";
                  return (
                    <td
                      key={cell.id}
                      className={`px-3 py-1 whitespace-nowrap border-r border-border/75 last:border-r-0 ${
                        align === "right" ? "text-right" : align === "center" ? "text-center" : "text-left"
                      } ${pinLeft ? `sticky left-0 z-10 ${ri % 2 === 1 ? "bg-grid-row-alt" : "bg-background"}` : ""} ${cellCls}`}
                      style={mono ? MONO : undefined}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  );
                })}
              </tr>
            );
          })}
          {rows.length === 0 && (
            <tr>
              <td
                colSpan={tanstackColumns.length}
                className="px-3 py-8 text-center text-muted-foreground"
              >
                {emptyMessage}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
