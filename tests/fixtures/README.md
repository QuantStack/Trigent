# Test Fixtures for Rich Issue MCP

This directory contains test data for comprehensive testing of the Rich Issue MCP system.

## Test Data Structure

### Issues (Initial Data)
10 sample issues covering 3 main subjects to test similarity detection:

#### Subject 1: Notebook Cell Execution (4 issues)
- **Issue 1001**: Cell execution fails with undefined variable error
- **Issue 1005**: Notebook kernel becomes unresponsive during long operations  
- **Issue 1008**: Cell output gets corrupted with large data visualizations
- **Issue 1010**: Cell execution order indicators are confusing

#### Subject 2: Keyboard Shortcuts (3 issues)
- **Issue 1002**: Ctrl+S shortcut conflicts with browser save
- **Issue 1006**: Custom keyboard shortcuts don't persist across sessions
- **Issue 1009**: Esc key doesn't exit command mode in notebook

#### Subject 3: File Browser Navigation (3 issues)
- **Issue 1003**: File browser doesn't refresh when files are added externally
- **Issue 1004**: File browser shows outdated file sizes  
- **Issue 1007**: File browser navigation is slow with large directories

### Updated Issues
Contains updated versions of some issues to test update functionality:

- **Issue 1001**: State changed to CLOSED, new comment added
- **Issue 1005**: New progress comment added
- **Issue 1011**: Completely new issue (UI theming)

## Expected Similarity Groups

When embeddings are generated, issues should cluster by subject:

1. **notebook_execution**: Issues 1001, 1005, 1008, 1010
2. **keyboard_shortcuts**: Issues 1002, 1006, 1009
3. **file_browser**: Issues 1003, 1004, 1007

## Cross-References

Some issues reference each other:
- Issue 1001 ↔ Issue 1005 (notebook execution problems)
- Issue 1003 ↔ Issue 1004 (file browser refresh issues)

## Test Scenarios

### 1. Pull Testing
- Initial pull: Load all 10 issues
- Update pull: Load changes (1001 closed, 1005 updated, 1011 added)

### 2. Enrichment Testing
- Verify embeddings are added
- Check similarity calculations work correctly
- Validate metric calculations (reactions, comments, etc.)

### 3. MCP Function Testing
- Similarity search should group issues by subject
- Cross-reference lookup should work
- Recommendation functions should operate correctly
- Export and filtering functions should work

## Data Format

Each issue JSON file contains:
- Basic GitHub issue fields (number, title, body, state, etc.)
- Author information
- Labels and assignees
- Reaction counts
- Comments array with reactions
- Cross-references to other issues
- Subject tag for testing validation