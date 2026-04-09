/**
 * PropertyPanel — right-side panel showing bond/account properties.
 *
 * Scans the workspace for all bond_target and account_target blocks,
 * groups by name, and lets the user edit properties in one place.
 * Edits propagate to ALL blocks with the same name.
 */
import React, { useCallback, useEffect, useState } from "react";
import { MONO } from "../../lib/format";

interface BondProps {
  name: string;
  bondType: string;
  faceAmt: number;
  coupon: number;
  accrual: string;
  blockIds: string[];
}

interface AccountProps {
  name: string;
  accountType: string;
  initialMode: string;
  initialAmt: number;
  blockIds: string[];
}

interface PropertyPanelProps {
  workspace: any;
}

function scanWorkspace(workspace: any): { bonds: BondProps[]; accounts: AccountProps[] } {
  const bondMap = new Map<string, BondProps>();
  const accountMap = new Map<string, AccountProps>();

  if (!workspace) return { bonds: [], accounts: [] };

  const allBlocks = workspace.getAllBlocks(false);
  for (const block of allBlocks) {
    if (block.type === "bond_target") {
      const name = block.getFieldValue("NAME") || "?";
      if (!bondMap.has(name)) {
        bondMap.set(name, {
          name,
          bondType: block.getFieldValue("BOND_TYPE") || "FIXED",
          faceAmt: block.getFieldValue("FACE_AMT") || 0,
          coupon: block.getFieldValue("COUPON") || 0,
          accrual: block.getFieldValue("ACCRUAL") || "30_360",
          blockIds: [],
        });
      }
      bondMap.get(name)!.blockIds.push(block.id);
    } else if (block.type === "account_target") {
      const name = block.getFieldValue("ACCOUNT_TYPE") || "?";
      if (!accountMap.has(name)) {
        const legacyPct = block.getFieldValue("INITIAL_PCT");
        accountMap.set(name, {
          name,
          accountType: block.getFieldValue("ACCOUNT_TYPE") || "RESERVE",
          initialMode: block.getFieldValue("INITIAL_MODE") || "PCT_STACK",
          initialAmt:
            block.getFieldValue("INITIAL_AMT") ??
            (legacyPct != null ? legacyPct : 0),
          blockIds: [],
        });
      }
      accountMap.get(name)!.blockIds.push(block.id);
    }
  }

  return {
    bonds: Array.from(bondMap.values()),
    accounts: Array.from(accountMap.values()),
  };
}

function syncBondField(workspace: any, name: string, field: string, value: any) {
  if (!workspace) return;
  const allBlocks = workspace.getAllBlocks(false);
  for (const block of allBlocks) {
    if (block.type === "bond_target" && block.getFieldValue("NAME") === name) {
      const f = block.getField(field);
      if (f) f.setValue(value);
    }
  }
}

function syncAccountField(workspace: any, accountType: string, field: string, value: any) {
  if (!workspace) return;
  const allBlocks = workspace.getAllBlocks(false);
  for (const block of allBlocks) {
    if (block.type === "account_target" && block.getFieldValue("ACCOUNT_TYPE") === accountType) {
      const f = block.getField(field);
      if (f) f.setValue(value);
    }
  }
}

export default function PropertyPanel({ workspace }: PropertyPanelProps) {
  const [bonds, setBonds] = useState<BondProps[]>([]);
  const [accounts, setAccounts] = useState<AccountProps[]>([]);

  const refresh = useCallback(() => {
    const { bonds: b, accounts: a } = scanWorkspace(workspace);
    setBonds(b);
    setAccounts(a);
  }, [workspace]);

  useEffect(() => {
    refresh();
    if (!workspace) return;
    const listener = () => setTimeout(refresh, 100);
    workspace.addChangeListener(listener);
    return () => workspace.removeChangeListener(listener);
  }, [workspace, refresh]);

  return (
    <div className="flex flex-col gap-3 text-xs">
      {bonds.length > 0 && (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
            Bonds
          </div>
          {bonds.map((b) => (
            <div key={b.name} className="flex items-center gap-2 py-1 border-b border-border">
              <span className="font-medium text-foreground w-8" style={MONO}>{b.name}</span>
              <span className="text-muted-foreground">{b.bondType}</span>
              <input
                type="number"
                value={b.faceAmt}
                onChange={(e) => {
                  const v = parseFloat(e.target.value) || 0;
                  syncBondField(workspace, b.name, "FACE_AMT", v);
                  refresh();
                }}
                className="w-24 px-1 py-0.5 bg-input-background border border-border rounded text-foreground"
                style={MONO}
              />
              <span className="text-muted-foreground">$</span>
              <input
                type="number"
                value={b.coupon}
                step={0.01}
                onChange={(e) => {
                  const v = parseFloat(e.target.value) || 0;
                  syncBondField(workspace, b.name, "COUPON", v);
                  refresh();
                }}
                className="w-14 px-1 py-0.5 bg-input-background border border-border rounded text-foreground"
                style={MONO}
              />
              <span className="text-muted-foreground">cpn</span>
              <span className="text-muted-foreground ml-auto">
                {b.blockIds.length}x
              </span>
            </div>
          ))}
        </div>
      )}

      {accounts.length > 0 && (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
            Accounts
          </div>
          {accounts.map((a) => (
            <div key={a.name} className="flex flex-wrap items-center gap-2 py-1 border-b border-border">
              <span className="font-medium text-foreground" style={MONO}>{a.name}</span>
              <select
                value={a.initialMode}
                onChange={(e) => {
                  syncAccountField(workspace, a.name, "INITIAL_MODE", e.target.value);
                  refresh();
                }}
                className="px-1 py-0.5 bg-input-background border border-border rounded text-foreground text-[10px]"
              >
                <option value="PCT_STACK">% bond stack</option>
                <option value="FIXED_DOLLAR">$ amount</option>
              </select>
              <input
                type="number"
                value={a.initialAmt}
                step={a.initialMode === "FIXED_DOLLAR" ? 1 : 0.01}
                onChange={(e) => {
                  const v = parseFloat(e.target.value) || 0;
                  syncAccountField(workspace, a.name, "INITIAL_AMT", v);
                  refresh();
                }}
                className="w-24 px-1 py-0.5 bg-input-background border border-border rounded text-foreground"
                style={MONO}
              />
              <span className="text-muted-foreground text-[10px]">
                {a.initialMode === "FIXED_DOLLAR" ? "$" : "%"}
              </span>
              <span className="text-muted-foreground ml-auto text-[10px]">
                {a.blockIds.length}×
              </span>
            </div>
          ))}
        </div>
      )}

      {bonds.length === 0 && accounts.length === 0 && (
        <div className="text-muted-foreground italic py-4 text-center">
          Add bond or account targets to pay rules to see properties here
        </div>
      )}
    </div>
  );
}
