export type MenuPageId = "agents" | "usage" | "theme" | "dispatch" | "roles" | "project";

export type MenuPageItem = {
  id: MenuPageId;
  label: string;
  title: string;
  hint?: string;
  type: "modal" | "page" | "action";
};

export const MENU_PAGES: MenuPageItem[] = [
  { id: "agents", label: "代理", title: "代理設定", type: "modal" },
  { id: "usage", label: "用量", title: "用量統計", type: "page" },
  { id: "theme", label: "主題", title: "主題設定", type: "modal" },
  { id: "dispatch", label: "派工", title: "派工設定", type: "page" },
  { id: "roles", label: "角色", title: "角色與素材", hint: "定義角色原則、技能與素材包套用", type: "page" },
  { id: "project", label: "專案", title: "更換專案", type: "action" },
];
