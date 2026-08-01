import type { Metadata } from "next";
import { SettingsScreen } from "../../components/settings-screen";

export const metadata: Metadata = {
  title: "Settings — Graphify",
  description: "Account preferences and connection details.",
};

export default function SettingsPage() {
  return <SettingsScreen />;
}
