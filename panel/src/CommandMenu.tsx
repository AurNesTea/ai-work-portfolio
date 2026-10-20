import { MENU_PAGES, MenuPageId } from "./menuPages";

type Props = {
  onSelect?: (id: MenuPageId) => void;
  onOpenAgents?: () => void;
  onOpenUsage?: () => void;
  onOpenTheme?: () => void;
  onOpenDispatch?: () => void;
  onOpenRoles?: () => void;
  onChooseRoot?: () => void;
};

export function CommandMenu({
  onSelect,
  onOpenAgents,
  onOpenUsage,
  onOpenTheme,
  onOpenDispatch,
  onOpenRoles,
  onChooseRoot,
}: Props) {
  function handleClick(id: MenuPageId) {
    if (onSelect) {
      onSelect(id);
      return;
    }
    if (id === "agents") onOpenAgents?.();
    else if (id === "usage") onOpenUsage?.();
    else if (id === "theme") onOpenTheme?.();
    else if (id === "dispatch") onOpenDispatch?.();
    else if (id === "roles") onOpenRoles?.();
    else if (id === "project") onChooseRoot?.();
  }

  return (
    <nav className="command-menu" aria-label="功能選單">
      <p className="command-menu-title">選單</p>
      <div className="command-grid">
        {MENU_PAGES.map((page) => (
          <button
            key={page.id}
            type="button"
            className="command-cell"
            onClick={() => handleClick(page.id)}
          >
            {page.label}
          </button>
        ))}
      </div>
    </nav>
  );
}
