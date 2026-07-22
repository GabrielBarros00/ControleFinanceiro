import * as React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { LayoutDashboard, CreditCard, Landmark, BarChart3, Settings, Repeat, Users, FileUp, Plus, Check, ChevronsUpDown, Wallet } from 'lucide-react';
import { cn } from "@/lib/utils";
import { useWorkspaces, type Workspace } from '@/hooks/use-workspaces';
import { useAuth } from '@/hooks/use-auth';
import { WorkspaceCreateDialog } from '@/components/workspace/WorkspaceCreateDialog';

const menuItems = [
  { icon: LayoutDashboard, label: 'Dashboard', path: '/' },
  { icon: Wallet, label: 'Rendas', path: '/income' },
  { icon: CreditCard, label: 'Cartões', path: '/cards' },
  { icon: Landmark, label: 'Financiamentos', path: '/financing' },
  { icon: BarChart3, label: 'Relatórios', path: '/reports' },
  { icon: Repeat, label: 'Recorrência', path: '/recurring' },
  { icon: Users, label: 'Dívidas', path: '/debts' },
  { icon: FileUp, label: 'Importar', path: '/import' },
  { icon: Settings, label: 'Configurações', path: '/settings' },
];

function WorkspaceSwitcher() {
  const { workspaces, currentWorkspace, switchWorkspace } = useWorkspaces();
  const { user } = useAuth();
  const [open, setOpen] = React.useState(false);
  const [createOpen, setCreateOpen] = React.useState(false);
  const containerRef = React.useRef<HTMLDivElement>(null);

  // Só faz sentido indicar "de quem é" quando o workspace é compartilhado
  const sharedHint = (ws: Workspace): string | null => {
    if ((ws.member_count ?? 1) <= 1) return null;
    if (ws.owner_user_id && ws.owner_user_id === user?.id) return 'Compartilhado por você';
    return ws.owner_name ? `de ${ws.owner_name}` : 'Compartilhado';
  };

  React.useEffect(() => {
    const onClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, []);

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full bg-accent/50 rounded-2xl p-4 border border-border text-left hover:bg-accent/70 transition-colors"
      >
        <p className="text-[10px] text-muted-foreground mb-2 uppercase tracking-widest font-bold">Workspace</p>
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <div className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse shrink-0" />
            <div className="min-w-0">
              <span className="block text-sm font-semibold truncate">
                {currentWorkspace?.name ?? 'Selecione...'}
              </span>
              {currentWorkspace && sharedHint(currentWorkspace) && (
                <span className="flex items-center gap-1 text-[10px] text-muted-foreground truncate">
                  <Users className="h-3 w-3 shrink-0" /> {sharedHint(currentWorkspace)}
                </span>
              )}
            </div>
          </div>
          <ChevronsUpDown className="h-4 w-4 text-muted-foreground shrink-0" />
        </div>
      </button>

      {open && (
        <div className="absolute bottom-full mb-2 left-0 right-0 bg-card border border-border rounded-xl shadow-2xl overflow-hidden z-50 animate-in fade-in slide-in-from-bottom-2 duration-150">
          <div className="max-h-56 overflow-y-auto py-1">
            {workspaces.map((ws) => (
              <button
                key={ws.id}
                type="button"
                onClick={() => { switchWorkspace(ws.id); setOpen(false); }}
                className={cn(
                  "w-full flex items-center justify-between gap-2 px-4 py-2.5 text-sm hover:bg-accent transition-colors",
                  ws.id === currentWorkspace?.id ? "font-bold text-primary" : "text-foreground"
                )}
              >
                <div className="flex flex-col min-w-0 text-left">
                  <span className="truncate">{ws.name}</span>
                  {sharedHint(ws) && (
                    <span className="flex items-center gap-1 text-[10px] font-normal text-muted-foreground truncate">
                      <Users className="h-3 w-3 shrink-0" /> {sharedHint(ws)}
                    </span>
                  )}
                </div>
                {ws.id === currentWorkspace?.id && <Check className="h-4 w-4 shrink-0" />}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => { setOpen(false); setCreateOpen(true); }}
            className="w-full flex items-center gap-2 px-4 py-2.5 text-sm text-primary font-semibold border-t border-border hover:bg-accent transition-colors"
          >
            <Plus className="h-4 w-4" /> Criar workspace
          </button>
        </div>
      )}

      <WorkspaceCreateDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}

export function Sidebar() {
  const location = useLocation();

  return (
    <aside className="w-64 border-r bg-card flex flex-col h-screen sticky top-0">
      <div className="p-8">
        <h1 className="text-xl font-bold tracking-tighter flex items-center gap-2">
          <div className="w-8 h-8 bg-primary rounded-lg flex items-center justify-center shadow-lg shadow-primary/20">
            <Landmark className="h-5 w-5 text-primary-foreground" />
          </div>
          CFv4 <span className="text-muted-foreground font-normal">Pro</span>
        </h1>
      </div>

      <nav className="flex-1 px-4 space-y-2">
        {menuItems.map((item) => (
          <Link
            key={item.path}
            to={item.path}
            className={cn(
              "flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200 group",
              location.pathname === item.path 
                ? "bg-primary text-primary-foreground shadow-lg shadow-primary/20" 
                : "text-muted-foreground hover:text-foreground hover:bg-accent"
            )}
          >
            <item.icon className={cn(
              "h-5 w-5 transition-transform duration-200",
              location.pathname === item.path ? "scale-110" : "group-hover:scale-110"
            )} />
            <span className="font-medium">{item.label}</span>
          </Link>
        ))}
      </nav>

      <div className="p-4 mt-auto">
        <WorkspaceSwitcher />
      </div>
    </aside>
  );
}
