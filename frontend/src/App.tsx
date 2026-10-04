import { useEffect, useRef, useState } from 'react';
import { Content, Theme } from '@carbon/react';
import { AppHeader } from './components/AppHeader';
import { AppSideNav } from './components/AppSideNav';
import { AskInput } from './components/AskInput';
import { AnswerWorkspace } from './components/AnswerWorkspace';
import { GuidePanel } from './components/GuidePanel';
import { HowItWasBuilt } from './components/pages/HowItWasBuilt';
import { MakeYourOwn } from './components/pages/MakeYourOwn';
import { useAsk } from './hooks/useAsk';
import { ROUTE_HASH, useHashRoute } from './hooks/useHashRoute';
import { useTheme } from './hooks/useTheme';

export function App() {
  const { entries, busy, submit, clear } = useAsk();
  const { theme, toggle } = useTheme();
  const [guideOpen, setGuideOpen] = useState(false);
  const route = useHashRoute();
  const pageRef = useRef<HTMLDivElement>(null);

  // A page opened from the side navigation starts at the top, not wherever
  // the previous page was scrolled to.
  useEffect(() => {
    pageRef.current?.scrollTo({ top: 0 });
  }, [route]);

  // g100 and g10 are Carbon's dark and light greyscale themes. Dark is the
  // default; the preference is shared with the login page so the two halves
  // of the application agree.
  const carbonTheme = theme === 'light' ? 'g10' : 'g100';

  // An example question asked from the guide is answered on the Ask page,
  // whichever page the guide was opened over.
  const askFromGuide = (question: string) => {
    window.location.hash = ROUTE_HASH.ask;
    submit(question);
  };

  // Only the content area changes between pages. The conversation lives in
  // useAsk above, so it is still there when the visitor comes back to Ask.
  return (
    <Theme theme={carbonTheme} className="archer-theme">
      <AppHeader theme={theme} onToggleTheme={toggle} onClear={clear} />
      <AppSideNav route={route} onOpenGuide={() => setGuideOpen(true)} />
      <Content id="main-content" className="archer-content">
        {route === 'ask' ? (
          <div className="archer-workspace">
            <AnswerWorkspace entries={entries} busy={busy} onAsk={submit} />
            <AskInput busy={busy} onSubmit={submit} />
          </div>
        ) : (
          <div className="archer-page" ref={pageRef}>
            {route === 'how-it-was-built' ? <HowItWasBuilt /> : <MakeYourOwn />}
          </div>
        )}
      </Content>
      <GuidePanel
        open={guideOpen}
        busy={busy}
        onClose={() => setGuideOpen(false)}
        onAsk={askFromGuide}
      />
    </Theme>
  );
}
