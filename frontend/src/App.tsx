import { useState } from 'react';
import { Content, Theme } from '@carbon/react';
import { AppHeader } from './components/AppHeader';
import { AppSideNav } from './components/AppSideNav';
import { AskInput } from './components/AskInput';
import { AnswerWorkspace } from './components/AnswerWorkspace';
import { SchemaPanel } from './components/SchemaPanel';
import { useAsk } from './hooks/useAsk';
import { useTheme } from './hooks/useTheme';

export function App() {
  const { entries, busy, submit, clear } = useAsk();
  const { theme, toggle } = useTheme();
  const [schemaOpen, setSchemaOpen] = useState(false);

  // g100 and g10 are Carbon's dark and light greyscale themes. Dark is the
  // default; the preference is shared with the login page so the two halves
  // of the application agree.
  const carbonTheme = theme === 'light' ? 'g10' : 'g100';

  return (
    <Theme theme={carbonTheme} className="archer-theme">
      <AppHeader theme={theme} onToggleTheme={toggle} onClear={clear} />
      <AppSideNav onOpenSchema={() => setSchemaOpen(true)} />
      <Content id="main-content" className="archer-content">
        <div className="archer-workspace">
          <AnswerWorkspace entries={entries} />
          <AskInput busy={busy} onSubmit={submit} />
        </div>
      </Content>
      <SchemaPanel open={schemaOpen} onClose={() => setSchemaOpen(false)} />
    </Theme>
  );
}
