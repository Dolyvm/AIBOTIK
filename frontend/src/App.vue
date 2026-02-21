<script setup>
import { ref } from 'vue'

const message = ref('Hello World!')

function reverseMessage() {
  message.value = message.value.split('').reverse().join('')
}

function notify() {
  alert('navigation was prevented.')
}
</script>

<template>

  <div></div>

</template>

<style>
button, a {
  display: block;
  margin-bottom: 1em;
}
</style>