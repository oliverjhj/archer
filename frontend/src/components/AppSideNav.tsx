import type { MouseEvent } from 'react';
import {
  SideNav,
  SideNavDivider,
  SideNavItems,
  SideNavLink,
} from '@carbon/react';
import { Branch, Chat, Help, Information, Rocket } from '@carbon/icons-react';
import { ROUTE_HASH, type Route } from '../hooks/useHashRoute';

export const REPO_URL = 'https://github.com/oliverjhj/archer';

interface AppSideNavProps {
  route: Route;
  onOpenGuide: () => void;
}

// Primary side navigation (IBM Carbon UI Shell).
//
// Every item here does something: a link that goes nowhere makes the whole
// interface read as a mockup.
export function AppSideNav({ route, onOpenGuide }: AppSideNavProps) {
  return (
    <SideNav
      aria-label="Primary navigation"
      isFixedNav
      expanded
      isChildOfHeader={false}
    >
      <SideNavItems>
        <SideNavLink renderIcon={Chat} href={ROUTE_HASH.ask} isActive={route === 'ask'}>
          Ask
        </SideNavLink>
        <SideNavLink
          renderIcon={Information}
          href="#"
          onClick={(event: MouseEvent) => {
            event.preventDefault();
            onOpenGuide();
          }}
        >
          How to use Archer
        </SideNavLink>
        <SideNavDivider />
        <SideNavLink
          renderIcon={Rocket}
          href={ROUTE_HASH['how-it-was-built']}
          isActive={route === 'how-it-was-built'}
        >
          How it was built
        </SideNavLink>
        <SideNavLink
          renderIcon={Branch}
          href={ROUTE_HASH['make-your-own']}
          isActive={route === 'make-your-own'}
        >
          Make your own
        </SideNavLink>
        <SideNavDivider />
        <SideNavLink
          renderIcon={Help}
          href={REPO_URL}
          target="_blank"
          rel="noopener noreferrer"
        >
          Source and docs
        </SideNavLink>
      </SideNavItems>
    </SideNav>
  );
}
