import assert from 'node:assert/strict'
import test from 'node:test'
import { authDestination } from '../src/lib/authDestination.ts'

test('successful authentication defaults to the homepage', () => {
  assert.equal(authDestination(null), '/')
})

test('an explicitly requested internal route is preserved', () => {
  assert.equal(authDestination('/history'), '/history')
})

test('external redirect destinations are rejected', () => {
  assert.equal(authDestination('//example.com'), '/')
  assert.equal(authDestination('https://example.com'), '/')
})
