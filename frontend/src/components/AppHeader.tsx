import {
  Header,
  HeaderGlobalAction,
  HeaderGlobalBar,
  HeaderName,
  SkipToContent,
} from '@carbon/react';
import { Asleep, Light, Reset } from '@carbon/icons-react';
import type { ThemeName } from '../hooks/useTheme';

interface AppHeaderProps {
  theme: ThemeName;
  onToggleTheme: () => void;
  onClear: () => void;
}

// Top application bar (IBM Carbon UI Shell).
export function AppHeader({ theme, onToggleTheme, onClear }: AppHeaderProps) {
  const switchingToLight = theme === 'dark';

  return (
    <Header aria-label="Archer Text-to-SQL">
      <SkipToContent />
      <HeaderName href="#" prefix="Archer">
        Text-to-SQL
      </HeaderName>
      <HeaderGlobalBar>
        {/*
          The label describes the theme you would switch TO, not the one you
          are in. Labelling it with the current state reads as a status
          display, and people click it expecting nothing to happen.
        */}
        <HeaderGlobalAction
          aria-label={switchingToLight ? 'Switch to light theme' : 'Switch to dark theme'}
          tooltipAlignment="end"
          onClick={onToggleTheme}
        >
          {switchingToLight ? <Light size={20} /> : <Asleep size={20} />}
        </HeaderGlobalAction>
        {/*
          "Clear conversation", not "New chat": nothing is saved, so "new"
          would imply a history of earlier chats that does not exist.
        */}
        <HeaderGlobalAction
          aria-label="Clear conversation"
          tooltipAlignment="end"
          onClick={onClear}
        >
          <Reset size={20} />
        </HeaderGlobalAction>
      </HeaderGlobalBar>
    </Header>
  );
}
