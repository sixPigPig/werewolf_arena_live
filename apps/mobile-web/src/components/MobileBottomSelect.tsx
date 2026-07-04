import {
  type MouseEvent,
  useMemo,
  useRef,
  useState,
} from "react";
import { Picker } from "antd-mobile";
import { ChevronDown } from "lucide-react";

export type MobileBottomSelectOption<TValue extends string = string> = {
  label: string;
  value: TValue;
};

type MobileBottomSelectProps<TValue extends string = string> = {
  className?: string;
  label: string;
  onChange: (value: TValue) => void;
  options: MobileBottomSelectOption<TValue>[];
  value: TValue;
};

export function MobileBottomSelect<TValue extends string = string>({
  className,
  label,
  onChange,
  options,
  value,
}: MobileBottomSelectProps<TValue>) {
  const [isOpen, setIsOpen] = useState(false);
  const [draftValue, setDraftValue] = useState<TValue>(value);
  const draftValueRef = useRef<TValue>(value);
  const selectedOption = useMemo(
    () => options.find((option) => option.value === value) ?? options[0],
    [options, value],
  );
  const selectedLabel = selectedOption?.label ?? "";
  const pickerTitle = `选择${label}筛选`;

  const openPicker = () => {
    draftValueRef.current = value;
    setDraftValue(value);
    setIsOpen(true);
  };

  const updateDraftValue = (nextValue: unknown[]) => {
    const nextSelectedValue = nextValue[0];

    if (typeof nextSelectedValue === "string") {
      const typedNextValue = nextSelectedValue as TValue;

      draftValueRef.current = typedNextValue;
      setDraftValue(typedNextValue);
    }
  };

  const updateDraftValueByLabel = (nextLabel: string) => {
    const nextOption = options.find((option) => option.label === nextLabel);

    if (!nextOption) return;

    draftValueRef.current = nextOption.value;
    setDraftValue(nextOption.value);
  };

  const syncAccessiblePickerClick = (event: MouseEvent) => {
    const target = event.target;

    if (!(target instanceof HTMLElement)) return;

    const pickerButton = target.closest<HTMLElement>(
      '[role="button"][aria-label^="选择上一项："], [role="button"][aria-label^="选择下一项："]',
    );
    const ariaLabel = pickerButton?.getAttribute("aria-label");

    if (!ariaLabel) return;

    updateDraftValueByLabel(ariaLabel.replace(/^选择[上下]一项：/, ""));
  };

  return (
    <Picker
      cancelText="取消"
      closeOnMaskClick
      columns={[
        options.map((option) => ({
          label: option.label,
          value: option.value,
        })),
      ]}
      confirmText="确定"
      onClick={syncAccessiblePickerClick}
      onCancel={() => setIsOpen(false)}
      onClose={() => setIsOpen(false)}
      onConfirm={() => {
        onChange(draftValueRef.current);
        setIsOpen(false);
      }}
      onSelect={updateDraftValue}
      popupClassName="mobile-bottom-select-picker-popup"
      title={pickerTitle}
      value={[isOpen ? draftValue : value]}
      visible={isOpen}
    >
      {() => (
        <div className={["mobile-profile-select", className].filter(Boolean).join(" ")}>
          <span>{label}</span>
          <button
            aria-expanded={isOpen}
            aria-haspopup="dialog"
            aria-label={`${label}筛选，当前 ${selectedLabel}`}
            className="mobile-profile-select-trigger"
            onClick={openPicker}
            type="button"
          >
            <span>{selectedLabel}</span>
            <ChevronDown
              aria-hidden="true"
              className="mobile-profile-select-chevron"
            />
          </button>
        </div>
      )}
    </Picker>
  );
}
