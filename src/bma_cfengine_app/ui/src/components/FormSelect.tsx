import React from "react";
import { control, cx } from "./system/ui";

const BASE_SELECT_CLASS = control.inputBase;

type FormSelectProps = React.SelectHTMLAttributes<HTMLSelectElement>;

export default function FormSelect({ className, children, ...props }: FormSelectProps) {
  const mergedClassName = cx(BASE_SELECT_CLASS, className);
  return (
    <select {...props} className={mergedClassName}>
      {children}
    </select>
  );
}
